import io
import pytest
import pandas as pd
from fastapi.testclient import TestClient

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JSON = {"accept": "application/json"}

@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db)
    import importlib, app.db as adb, app.main as amain
    importlib.reload(adb)
    importlib.reload(amain)
    from app.main import app as fastapp
    from app.db import init_db
    init_db(db)
    return TestClient(fastapp)

def test_dashboard_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Schedella" in r.text

def test_nuova_form_returns_200(client):
    r = client.get("/nuova")
    assert r.status_code == 200

def test_storia_returns_200(client):
    r = client.get("/storia")
    assert r.status_code == 200

def test_analisi_returns_200(client):
    r = client.get("/analisi")
    assert r.status_code == 200

def _excel_bytes():
    df = pd.DataFrame({
        "Partita": ["Milan","Juve","Roma","Torino"],
        "Away": ["Inter","Napoli","Lazio","Genoa"],
        "Giorno/Ora": ["dom 20:45"]*4,
        "Cos": ["X","","",""],
    })
    buf = io.BytesIO()
    blank = pd.DataFrame([[""] * 4])
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        blank.to_excel(w, index=False, header=False)
        df.to_excel(w, index=False, startrow=1)
    return buf.getvalue()

def _create_session(client, players=1, per_player=3, selection_mode="none", cos_column="Cos"):
    """Two-step flow: upload → configura → sorteggio. Returns session_id."""
    data = _excel_bytes()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # Step 1: upload file
    r1 = client.post("/nuova", files={"excel_file": ("test.xlsx", data, mime)},
                     follow_redirects=False)
    assert r1.status_code in (302, 303)
    session_id = r1.headers["location"].split("/")[-1]
    # Step 2: configure
    r2 = client.post(f"/configura/{session_id}", data={
        "players": str(players), "per_player": str(per_player),
        "selection_mode": selection_mode,
        "cos_column": cos_column,
        "allow_4th": "", "use_odds": "",
    }, follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert "/sorteggio/" in r2.headers["location"]
    return int(r2.headers["location"].split("/")[-1])

def test_post_nuova_redirects_to_configura(client):
    data = _excel_bytes()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    r = client.post("/nuova", files={"excel_file": ("test.xlsx", data, mime)},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/configura/" in r.headers["location"]

def test_configura_redirects_to_sorteggio(client):
    _create_session(client)  # asserts internally

def test_sorteggio_page_loads(client):
    session_id = _create_session(client, per_player=2)
    r = client.get(f"/sorteggio/{session_id}")
    assert r.status_code == 200
    assert "Lancia" in r.text

def test_roll_pick_returns_fragment(client):
    session_id = _create_session(client, per_player=2)
    from app.db import get_schedelle_for_session
    import os
    db_path = os.environ.get("DB_PATH", "data/schedella.db")
    schedella_ids = get_schedelle_for_session(db_path, session_id)
    r = client.post(f"/sorteggio/{session_id}/roll/0",
                    data={"schedella_id": str(schedella_ids[0])},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "badge-pron" in r.text or "pronostico" in r.text.lower()

def test_save_result(client):
    session_id = _create_session(client, per_player=2)
    import os
    from app.db import get_schedelle_for_session
    db_path = os.environ.get("DB_PATH", "data/schedella.db")
    schedelle = get_schedelle_for_session(db_path, session_id)
    r = client.post(f"/storia/{schedelle[0]}/result",
                    data={"outcome": "won", "actual_multiplier": "12.5", "stake": "5"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200

def test_nuova_default_excel_button_and_upload(client, tmp_path, monkeypatch):
    import app.main as amain
    path = tmp_path / "Schedella2627.xlsx"
    path.write_bytes(_excel_bytes())
    monkeypatch.setattr(amain, "DEFAULT_EXCEL_PATH", str(path))
    assert "Usa Schedella2627.xlsx" in client.get("/nuova").text
    r = client.post("/nuova/default", follow_redirects=False)
    assert r.status_code == 303
    assert "/configura/" in r.headers["location"]
    assert client.get(r.headers["location"]).status_code == 200

def test_nuova_default_excel_missing(client, tmp_path, monkeypatch):
    import app.main as amain
    monkeypatch.setattr(amain, "DEFAULT_EXCEL_PATH", str(tmp_path / "missing.xlsx"))
    assert "/nuova/default" not in client.get("/nuova").text
    r = client.post("/nuova/default", follow_redirects=False)
    assert r.headers["location"] == "/nuova"

def test_nuova_upload_json_returns_redirect(client):
    r = client.post("/nuova", files={"excel_file": ("t.xlsx", _excel_bytes(), MIME)}, headers=JSON)
    assert r.status_code == 200 and r.json()["redirect"].startswith("/configura/")

def test_riapri_missing_json_redirects_to_nuova(client):
    r = client.post("/nuova/riapri/9999", headers=JSON)
    assert r.json() == {"redirect": "/nuova"}

def test_nuova_default_json(client, tmp_path, monkeypatch):
    import app.main as amain
    path = tmp_path / "Schedella2627.xlsx"
    path.write_bytes(_excel_bytes())
    monkeypatch.setattr(amain, "DEFAULT_EXCEL_PATH", str(path))
    assert client.post("/nuova/default", headers=JSON).json()["redirect"].startswith("/configura/")


def test_api_form_without_key(client, monkeypatch):
    monkeypatch.delenv("FOOTBALLDATA_KEY", raising=False)
    r = client.post("/api/form", json={"matches": ["Napoli - Roma"]})
    assert r.status_code == 200
    assert r.json()["error"]


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


def test_base_uses_tailwind_style_block(client):
    page = client.get("/").text
    assert 'type="text/tailwindcss"' in page
    assert 'id="progress-modal"' in page and "/static/progress.js" in page


def test_nuova_forms_use_progress(client):
    page = client.get("/nuova").text
    assert page.count("Progress.uploadForm(this)") >= 1


def test_configura_submit_uses_progress(client):
    r = client.post("/nuova", files={"excel_file": ("t.xlsx", _excel_bytes(), MIME)}, follow_redirects=False)
    page = client.get(r.headers["location"]).text
    assert "Progress.open(" in page and "indeterminate" in page

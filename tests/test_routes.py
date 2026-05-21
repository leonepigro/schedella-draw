import io
import pytest
import pandas as pd
from fastapi.testclient import TestClient

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

def test_post_nuova_redirects_to_sorteggio(client):
    data = _excel_bytes()
    r = client.post("/nuova", data={
        "players": "1", "per_player": "3",
        "allow_4th": "", "use_odds": "",
        "selection_mode": "cos", "cos_column": "Cos",
    }, files={"excel_file": ("test.xlsx", data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/sorteggio/" in r.headers["location"]

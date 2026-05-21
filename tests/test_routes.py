import pytest
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

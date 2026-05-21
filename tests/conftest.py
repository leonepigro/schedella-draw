import os
import pytest
import tempfile
from app.db import init_db, get_connection

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path

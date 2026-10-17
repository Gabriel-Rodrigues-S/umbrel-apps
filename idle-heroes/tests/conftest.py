"""Fixtures dos testes: banco temporário e cliente da API."""
import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c

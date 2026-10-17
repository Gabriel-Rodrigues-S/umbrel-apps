"""Migração do banco 1.0.0 -> 1.1.0 e helpers de campos."""
import sqlite3

import pytest

from app import db
from app.db import criar_tabelas, tier

# Esquema da 1.0.0 (só colunas antigas), independente do TABELAS novo.
ESQUEMA_1_0_0 = """
CREATE TABLE herois (id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
CREATE TABLE contas (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, servidor TEXT, vip INTEGER, notas TEXT);
CREATE TABLE medicoes (
  id INTEGER PRIMARY KEY,
  conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
  heroi_id INTEGER NOT NULL REFERENCES herois(id) ON DELETE CASCADE,
  data TEXT NOT NULL, poder INTEGER, ataque INTEGER, hp INTEGER, velocidade INTEGER,
  arvore INTEGER, nucleo TEXT, grimorio TEXT, notas TEXT
);
"""


@pytest.fixture
def banco_antigo(tmp_path, monkeypatch):
    caminho = str(tmp_path / "antigo.db")
    monkeypatch.setattr(db, "DB_PATH", caminho)
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA_1_0_0)
    con.execute("INSERT INTO herois (nome) VALUES ('Heroi A')")
    con.execute("INSERT INTO contas (nome) VALUES ('Conta X')")
    con.execute("INSERT INTO medicoes (conta_id, heroi_id, data, poder) VALUES (1, 1, '2026-01-01', 100)")
    con.commit()
    con.close()
    return caminho


def test_tier_faixas():
    assert tier(None) is None
    assert tier(0) is None
    assert tier(19) is None
    assert tier(20) == "T1"
    assert tier(39) == "T1"
    assert tier(40) == "T2"
    assert tier(67) == "T3"
    assert tier(99) == "T4"
    assert tier(100) == "T5"
    assert tier(120) == "T5"


def test_banco_antigo_ganha_colunas(banco_antigo):
    criar_tabelas()
    with db.conectar() as con:
        m = con.execute("SELECT * FROM medicoes").fetchone()
        c = con.execute("SELECT * FROM contas").fetchone()
    assert m["poder"] == 100
    assert m["armadura"] is None
    assert m["transicao"] is None
    assert m["equip_ressonancia"] is None
    assert "criada_em" in c.keys()


def test_migracao_idempotente(banco_antigo):
    criar_tabelas()
    criar_tabelas()


def test_duplicata_nao_impede_subir(banco_antigo):
    con = sqlite3.connect(banco_antigo)
    con.execute("INSERT INTO medicoes (conta_id, heroi_id, data, poder) VALUES (1, 1, '2026-01-01', 100)")
    con.commit()
    con.close()
    criar_tabelas()
    with db.conectar() as con:
        assert con.execute("SELECT COUNT(*) FROM medicoes").fetchone()[0] == 2


def test_api_generica_recusa_duplicata(cliente):
    cliente.post("/api/contas", json={"nome": "Conta X"})
    cliente.post("/api/herois", json={"nome": "Heroi A"})
    med = {"conta_id": 1, "heroi_id": 1, "data": "2026-01-01", "poder": 10}
    assert cliente.post("/api/medicoes", json=med).status_code == 201
    assert cliente.post("/api/medicoes", json=med).status_code == 400

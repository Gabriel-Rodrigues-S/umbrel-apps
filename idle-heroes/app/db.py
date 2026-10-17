"""Banco SQLite e o registro das tabelas que o CRUD expõe."""
import os
import sqlite3

DB_PATH = os.environ.get("IH_DB", "/app/data/idle-heroes.db")

# Cada tabela: colunas editáveis -> (tipo SQL, rótulo, tipo de campo na tela).
# Referências a outras tabelas usam o tipo de campo "ref:<tabela>".
TABELAS = {
    "herois": {
        "rotulo": "Heróis",
        "exibir": "nome",
        "colunas": {
            "nome": ("TEXT NOT NULL", "Nome", "text"),
            "titulo": ("TEXT", "Título", "text"),
            "classe": ("TEXT", "Classe", "text"),
            "faccao": ("TEXT", "Facção", "text"),
            "hp": ("INTEGER", "HP base", "number"),
            "ataque": ("INTEGER", "Ataque base", "number"),
            "armadura": ("INTEGER", "Armadura base", "number"),
            "velocidade": ("INTEGER", "Velocidade base", "number"),
            "fonte": ("TEXT", "Fonte", "text"),
            "notas": ("TEXT", "Notas", "textarea"),
        },
    },
    "habilidades": {
        "rotulo": "Habilidades",
        "exibir": "nome",
        "colunas": {
            "heroi_id": ("INTEGER NOT NULL REFERENCES herois(id) ON DELETE CASCADE", "Herói", "ref:herois"),
            "tipo": ("TEXT NOT NULL", "Tipo", "select:ativa,passiva_1,passiva_2,passiva_3,nucleo,transicao"),
            "nome": ("TEXT", "Nome", "text"),
            "efeito": ("TEXT", "Efeito", "textarea"),
            "sub_pura": ("TEXT", "Sublimação pura", "textarea"),
            "sub_profunda": ("TEXT", "Sublimação profunda", "textarea"),
            "sub_nobre": ("TEXT", "Sublimação nobre", "textarea"),
        },
    },
    "pivos": {
        "rotulo": "Pivôs espirituais",
        "exibir": "ramo",
        "colunas": {
            "heroi_id": ("INTEGER NOT NULL REFERENCES herois(id) ON DELETE CASCADE", "Herói", "ref:herois"),
            "ramo": ("TEXT NOT NULL", "Ramo", "text"),
            "ordem": ("INTEGER", "Ordem", "number"),
            "efeito": ("TEXT", "Efeito", "textarea"),
        },
    },
    "contas": {
        "rotulo": "Contas",
        "exibir": "nome",
        "colunas": {
            "nome": ("TEXT NOT NULL", "Nome", "text"),
            "servidor": ("TEXT", "Servidor", "text"),
            "vip": ("INTEGER", "VIP", "number"),
            "notas": ("TEXT", "Notas", "textarea"),
        },
    },
    "medicoes": {
        "rotulo": "Medições",
        "exibir": "data",
        "colunas": {
            "conta_id": ("INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE", "Conta", "ref:contas"),
            "heroi_id": ("INTEGER NOT NULL REFERENCES herois(id) ON DELETE CASCADE", "Herói", "ref:herois"),
            "data": ("TEXT NOT NULL", "Data", "date"),
            "poder": ("INTEGER", "Poder", "number"),
            "ataque": ("INTEGER", "Ataque", "number"),
            "hp": ("INTEGER", "HP", "number"),
            "velocidade": ("INTEGER", "Velocidade", "number"),
            "arvore": ("INTEGER", "Nível da árvore", "number"),
            "nucleo": ("TEXT", "Núcleo de origem", "text"),
            "grimorio": ("TEXT", "Grimório", "text"),
            "notas": ("TEXT", "Notas", "textarea"),
        },
    },
    "casinhas": {
        "rotulo": "Casinhas",
        "exibir": "id",
        "colunas": {
            "conta_id": ("INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE", "Conta", "ref:contas"),
            "proprietario_id": ("INTEGER REFERENCES herois(id) ON DELETE SET NULL", "Proprietário", "ref:herois"),
            "inquilino_id": ("INTEGER REFERENCES herois(id) ON DELETE SET NULL", "Inquilino", "ref:herois"),
            "nivel": ("INTEGER", "Nível", "number"),
            "transferencia_pct": ("REAL", "Transferência (%)", "number"),
            "velocidade_fixa": ("INTEGER", "Velocidade transferida", "number"),
            "aura_ataque": ("INTEGER", "Aura de ataque", "number"),
            "aura_hp": ("INTEGER", "Aura de HP", "number"),
            "atualizado_em": ("TEXT", "Atualizado em", "date"),
            "notas": ("TEXT", "Notas", "textarea"),
        },
    },
    "testes": {
        "rotulo": "Testes",
        "exibir": "titulo",
        "colunas": {
            "conta_id": ("INTEGER REFERENCES contas(id) ON DELETE SET NULL", "Conta", "ref:contas"),
            "data": ("TEXT NOT NULL", "Data", "date"),
            "titulo": ("TEXT NOT NULL", "Título", "text"),
            "mudanca": ("TEXT", "O que mudou", "textarea"),
            "antes": ("TEXT", "Antes", "textarea"),
            "depois": ("TEXT", "Depois", "textarea"),
            "conclusao": ("TEXT", "Conclusão", "textarea"),
        },
    },
}


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def criar_tabelas():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with conectar() as con:
        for nome, t in TABELAS.items():
            cols = ", ".join(f"{c} {sql}" for c, (sql, _, _) in t["colunas"].items())
            con.execute(f"CREATE TABLE IF NOT EXISTS {nome} (id INTEGER PRIMARY KEY, {cols})")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS herois_nome ON herois(nome)")

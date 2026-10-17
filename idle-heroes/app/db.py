"""Banco SQLite e o registro das tabelas que o CRUD expõe."""
import logging
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
            "criada_em": ("TEXT", "Criada em", "date"),
            "criada_em_aproximada": ("INTEGER", "Data aproximada", "bool"),
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
            "armadura": ("INTEGER", "Armadura", "number"),
            "velocidade": ("INTEGER", "Velocidade", "number"),
            "transicao": ("INTEGER", "Transição do Destino", "bool"),
            "transicao_em": ("TEXT", "Transição em", "date"),
            "arvore": ("INTEGER", "Nível da árvore (0 = sem árvore)", "number"),
            "nucleo": ("TEXT", "Núcleo de origem", "text"),
            "sublimacao": ("TEXT", "Sublimação", "text"),
            "grimorio": ("TEXT", "Grimório", "text"),
            "equipamento": ("TEXT", "Equipamento", "text"),
            "equip_estrelas": ("INTEGER", "Estrelas do equipamento", "number"),
            "equip_ressonancia": ("TEXT", "Ressonância do equipamento", "select:todas,parcial,nenhuma"),
            "artefato": ("TEXT", "Artefato", "text"),
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

# Números são sempre da data medida; estado vale até mudar (herdado de medição anterior).
NUMEROS = ("poder", "ataque", "hp", "armadura", "velocidade")
ESTADO = ("transicao", "transicao_em", "arvore", "nucleo", "sublimacao", "grimorio",
          "equipamento", "equip_estrelas", "equip_ressonancia", "artefato")


def tier(nivel):
    """Tier da árvore (T1 = 20-39 ... T5 = 100+); None se vazio ou abaixo de 20."""
    if nivel is None or nivel < 20:
        return None
    return f"T{min(nivel // 20, 5)}"


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
        migrar(con)


def migrar(con):
    """Adiciona colunas novas em bancos antigos e garante a unicidade da medição."""
    for nome, t in TABELAS.items():
        existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({nome})")}
        for c, (sql, _, _) in t["colunas"].items():
            if c not in existentes:
                con.execute(f"ALTER TABLE {nome} ADD COLUMN {c} {sql}")
    try:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS medicoes_unica ON medicoes(conta_id, heroi_id, data)")
    except sqlite3.IntegrityError:
        logging.warning("Medições duplicadas (conta, herói, data): índice único não criado")

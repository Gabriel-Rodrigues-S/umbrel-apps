"""Endpoint de sessão: grava várias medições de uma vez (upsert por conta, herói e data)."""
from fastapi import APIRouter, HTTPException

from .db import TABELAS, conectar

router = APIRouter()

CHAVES = {"conta_id", "heroi_id", "data"}
CAMPOS = [c for c in TABELAS["medicoes"]["colunas"] if c not in CHAVES]


def valor(v):
    """Texto vazio vira NULL, como no limpar() da API genérica."""
    return None if v == "" else v


@router.post("/api/sessao")
def gravar_sessao(corpo: dict):
    """Grava as medições de uma sessão numa única transação (tudo ou nada).

    Corpo: `{"conta_id": 1, "data": "AAAA-MM-DD", "herois": [{"heroi_id": 3, "poder": 100, ...}]}`.

    Para cada herói: se já existe medição da (conta, herói, data), atualiza só as
    chaves presentes no item (chave ausente não mexe; `null` ou `""` limpa); senão cria.

    ATENÇÃO: este endpoint NÃO herda nada da medição anterior. Quem chama (a tela
    ou o Claude, ao gravar uma sessão ditada) deve mandar os campos de estado
    (transicao, transicao_em, arvore, nucleo, sublimacao, grimorio, equipamento,
    equip_estrelas, equip_ressonancia, artefato) já herdados. Os números (poder,
    ataque, hp, armadura, velocidade) nunca se herdam: o que não for medido fica de fora.

    Resposta: `{"criadas": [ids], "atualizadas": [ids]}`.
    """
    conta_id, data, herois = corpo.get("conta_id"), corpo.get("data"), corpo.get("herois")
    if not isinstance(conta_id, int) or not data or not isinstance(data, str):
        raise HTTPException(400, "Informe conta_id (inteiro) e data (AAAA-MM-DD)")
    if not isinstance(herois, list) or not herois:
        raise HTTPException(400, "herois deve ser uma lista com ao menos um item")

    itens = []
    for item in herois:
        if not isinstance(item, dict) or not isinstance(item.get("heroi_id"), int):
            raise HTTPException(400, "Cada item de herois precisa de heroi_id (inteiro)")
        desconhecidas = set(item) - CHAVES - set(CAMPOS)
        if desconhecidas:
            raise HTTPException(400, f"Campos desconhecidos: {', '.join(sorted(desconhecidas))}")
        itens.append((item["heroi_id"], {c: valor(item[c]) for c in CAMPOS if c in item}))

    criadas, atualizadas = [], []
    try:
        with conectar() as con:
            # Conta e heróis validados antes de gravar: o UPDATE não passa por FK.
            if not con.execute("SELECT 1 FROM contas WHERE id = ?", (conta_id,)).fetchone():
                raise HTTPException(400, f"Conta {conta_id} não existe")
            for heroi_id, _ in itens:
                if not con.execute("SELECT 1 FROM herois WHERE id = ?", (heroi_id,)).fetchone():
                    raise HTTPException(400, f"Herói {heroi_id} não existe")

            for heroi_id, campos in itens:
                atual = con.execute(
                    "SELECT id FROM medicoes WHERE conta_id = ? AND heroi_id = ? AND data = ? ORDER BY id",
                    (conta_id, heroi_id, data),
                ).fetchone()
                if atual:
                    if campos:
                        sets = ", ".join(f"{c} = ?" for c in campos)
                        con.execute(f"UPDATE medicoes SET {sets} WHERE id = ?", [*campos.values(), atual["id"]])
                    atualizadas.append(atual["id"])
                else:
                    todos = {"conta_id": conta_id, "heroi_id": heroi_id, "data": data, **campos}
                    cols = ", ".join(todos)
                    marcas = ", ".join("?" for _ in todos)
                    cur = con.execute(f"INSERT INTO medicoes ({cols}) VALUES ({marcas})", list(todos.values()))
                    criadas.append(cur.lastrowid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"criadas": criadas, "atualizadas": atualizadas}

"""Endpoint de comparação: séries e ficha de cada par (conta, herói)."""
from fastapi import APIRouter, HTTPException

from .db import NUMEROS, conectar, tier

router = APIRouter()


def ler_pares(texto):
    """'1:3,2:3' -> [(1, 3), (2, 3)]; 400 se algum par vier mal formado."""
    pares = []
    for p in texto.split(","):
        try:
            conta, heroi = p.split(":")
            pares.append((int(conta), int(heroi)))
        except ValueError:
            raise HTTPException(400, f"Par inválido: {p!r} (use conta_id:heroi_id)")
    return pares


def ficha(con, conta_id, heroi_id):
    conta = con.execute("SELECT * FROM contas WHERE id = ?", (conta_id,)).fetchone()
    heroi = con.execute("SELECT * FROM herois WHERE id = ?", (heroi_id,)).fetchone()
    if not conta or not heroi:
        raise HTTPException(404, "Conta ou herói não encontrado")

    medicoes = []
    for m in con.execute(
        "SELECT * FROM medicoes WHERE conta_id = ? AND heroi_id = ? ORDER BY data, id", (conta_id, heroi_id)
    ):
        m = dict(m)
        m["arvore_tier"] = tier(m["arvore"])
        medicoes.append(m)

    # Números não são herdados: cada campo guarda o último valor realmente medido.
    ultimo_numero = {c: None for c in NUMEROS}
    for m in medicoes:
        for c in NUMEROS:
            if m[c] is not None:
                ultimo_numero[c] = {"valor": m[c], "data": m["data"]}

    casinhas = [
        {**dict(c), "inquilino": c["inquilino_nome"]}
        for c in con.execute(
            "SELECT c.*, i.nome AS inquilino_nome FROM casinhas c "
            "LEFT JOIN herois i ON i.id = c.inquilino_id "
            "WHERE c.conta_id = ? AND c.proprietario_id = ? ORDER BY c.id",
            (conta_id, heroi_id),
        )
    ]
    for c in casinhas:
        del c["inquilino_nome"]

    return {
        "conta": dict(conta),
        "heroi": dict(heroi),
        "medicoes": medicoes,
        "ultima": medicoes[-1] if medicoes else None,
        "ultimo_numero": ultimo_numero,
        "casinhas": casinhas,
    }


@router.get("/api/comparacao")
def comparar(pares: str):
    lista = ler_pares(pares)
    with conectar() as con:
        return [ficha(con, c, h) for c, h in lista]

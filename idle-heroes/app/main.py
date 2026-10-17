"""API do CRUD do Idle Heroes. O catálogo de heróis não vem no código: é
importado pela interface a partir do JSON da comunidade e fica só no volume."""
import json
import re

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from .db import TABELAS, conectar, criar_tabelas

app = FastAPI(title="Idle Heroes CRUD")


@app.on_event("startup")
def iniciar():
    criar_tabelas()


@app.get("/")
def index():
    # Sem interface própria por enquanto: a página inicial abre a tela automática da API.
    return RedirectResponse("docs")


@app.get("/api/meta")
def meta():
    return {
        nome: {
            "rotulo": t["rotulo"],
            "exibir": t["exibir"],
            "colunas": [{"nome": c, "rotulo": r, "campo": f} for c, (_, r, f) in t["colunas"].items()],
        }
        for nome, t in TABELAS.items()
    }


def tabela(nome):
    if nome not in TABELAS:
        raise HTTPException(404, "Tabela desconhecida")
    return TABELAS[nome]


def limpar(t, dados):
    """Mantém só colunas conhecidas e troca texto vazio por NULL."""
    return {c: (None if v == "" else v) for c, v in dados.items() if c in t["colunas"]}


@app.get("/api/{nome}")
def listar(nome: str, filtro: str = "", valor: str = ""):
    t = tabela(nome)
    sql, args = f"SELECT * FROM {nome}", []
    if filtro:
        if filtro not in t["colunas"]:
            raise HTTPException(400, "Filtro inválido")
        sql += f" WHERE {filtro} = ?"
        args.append(valor)
    sql += " ORDER BY id"
    with conectar() as con:
        return [dict(r) for r in con.execute(sql, args)]


@app.get("/api/{nome}/{id}")
def obter(nome: str, id: int):
    tabela(nome)
    with conectar() as con:
        r = con.execute(f"SELECT * FROM {nome} WHERE id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404, "Registro não encontrado")
    return dict(r)


@app.post("/api/{nome}", status_code=201)
def criar(nome: str, dados: dict):
    d = limpar(tabela(nome), dados)
    if not d:
        raise HTTPException(400, "Nenhum campo válido")
    cols = ", ".join(d)
    marcas = ", ".join("?" for _ in d)
    try:
        with conectar() as con:
            cur = con.execute(f"INSERT INTO {nome} ({cols}) VALUES ({marcas})", list(d.values()))
    except Exception as e:
        raise HTTPException(400, str(e))
    return obter(nome, cur.lastrowid)


@app.put("/api/{nome}/{id}")
def editar(nome: str, id: int, dados: dict):
    d = limpar(tabela(nome), dados)
    if not d:
        raise HTTPException(400, "Nenhum campo válido")
    sets = ", ".join(f"{c} = ?" for c in d)
    try:
        with conectar() as con:
            cur = con.execute(f"UPDATE {nome} SET {sets} WHERE id = ?", [*d.values(), id])
    except Exception as e:
        raise HTTPException(400, str(e))
    if cur.rowcount == 0:
        raise HTTPException(404, "Registro não encontrado")
    return obter(nome, id)


@app.delete("/api/{nome}/{id}", status_code=204)
def apagar(nome: str, id: int):
    tabela(nome)
    with conectar() as con:
        cur = con.execute(f"DELETE FROM {nome} WHERE id = ?", (id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "Registro não encontrado")


# --- importação do catálogo da comunidade ---

TIPOS_HABILIDADE = {
    "active_skill": "ativa",
    "passive_1": "passiva_1",
    "passive_2": "passiva_2",
    "passive_3": "passiva_3",
}


def numero(texto):
    digitos = re.sub(r"[^\d]", "", str(texto or ""))
    return int(digitos) if digitos else None


def separar_nome(completo):
    """'Lord of Fear - Aspen' -> ('Aspen', 'Lord of Fear'). Sem hífen, fica tudo no nome."""
    if "-" in completo:
        titulo, nome = completo.rsplit("-", 1)
        return nome.strip(), titulo.strip()
    return completo.strip(), None


def importar_catalogo(registros, fonte):
    resumo = {"novos": 0, "atualizados": 0}
    with conectar() as con:
        for h in registros:
            nome, titulo = separar_nome(h["hero"])
            campos = {
                "titulo": titulo,
                "classe": h.get("class"),
                "faccao": "Transcendence",
                "hp": numero(h.get("hp")),
                "ataque": numero(h.get("attack")),
                "armadura": numero(h.get("armor")),
                "velocidade": numero(h.get("speed")),
                "fonte": fonte,
            }
            existente = con.execute("SELECT id FROM herois WHERE nome = ?", (nome,)).fetchone()
            if existente:
                hid = existente["id"]
                sets = ", ".join(f"{c} = ?" for c in campos)
                con.execute(f"UPDATE herois SET {sets} WHERE id = ?", [*campos.values(), hid])
                # Habilidades e pivôs vêm só da fonte: são substituídos inteiros.
                con.execute("DELETE FROM habilidades WHERE heroi_id = ?", (hid,))
                con.execute("DELETE FROM pivos WHERE heroi_id = ?", (hid,))
                resumo["atualizados"] += 1
            else:
                cols = ", ".join(["nome", *campos])
                marcas = ", ".join("?" for _ in range(len(campos) + 1))
                hid = con.execute(f"INSERT INTO herois ({cols}) VALUES ({marcas})", [nome, *campos.values()]).lastrowid
                resumo["novos"] += 1

            for chave, tipo in TIPOS_HABILIDADE.items():
                s = h.get(chave) or {}
                sub = s.get("sublimations") or {}
                con.execute(
                    "INSERT INTO habilidades (heroi_id, tipo, nome, efeito, sub_pura, sub_profunda, sub_nobre) VALUES (?,?,?,?,?,?,?)",
                    (hid, tipo, s.get("name"), s.get("main_effect"), sub.get("pure"), sub.get("deep"), sub.get("noble")),
                )
            for chave, tipo in (("core_of_origin", "nucleo"), ("transition_skill", "transicao")):
                if h.get(chave):
                    con.execute(
                        "INSERT INTO habilidades (heroi_id, tipo, efeito) VALUES (?,?,?)", (hid, tipo, h[chave])
                    )
            for ramo, efeitos in (h.get("spiritual_pivots") or {}).items():
                for ordem, efeito in enumerate(efeitos, 1):
                    con.execute(
                        "INSERT INTO pivos (heroi_id, ramo, ordem, efeito) VALUES (?,?,?,?)",
                        (hid, ramo.replace("_", " ").title(), ordem, efeito),
                    )
    return resumo


@app.post("/api/importar/catalogo")
async def importar(arquivo: UploadFile):
    try:
        registros = json.loads(await arquivo.read())
        assert isinstance(registros, list) and all("hero" in r for r in registros)
    except Exception:
        raise HTTPException(400, "Arquivo não é o JSON de heróis esperado")
    return importar_catalogo(registros, f"MushroomGecko/Idle-Heroes-Transcendence-Heroes ({arquivo.filename})")

"""Testes do endpoint de comparação (dados inventados)."""


def criar(c, tabela, **dados):
    r = c.post(f"/api/{tabela}", json=dados)
    assert r.status_code == 201, r.text
    return r.json()


def cenario(c):
    x = criar(c, "contas", nome="Conta X", criada_em="2022-08-11", criada_em_aproximada=1)
    y = criar(c, "contas", nome="Conta Y")
    a = criar(c, "herois", nome="Heroi A")
    b = criar(c, "herois", nome="Heroi B")
    return x, y, a, b


def comparar(c, *pares):
    return c.get("/api/comparacao", params={"pares": ",".join(f"{p}:{h}" for p, h in pares)})


def test_dois_pares_mesmo_heroi_contas_diferentes(cliente):
    x, y, a, _ = cenario(cliente)
    criar(cliente, "medicoes", conta_id=x["id"], heroi_id=a["id"], data="2026-10-08", poder=100)
    criar(cliente, "medicoes", conta_id=y["id"], heroi_id=a["id"], data="2026-10-09", poder=200)
    r = comparar(cliente, (y["id"], a["id"]), (x["id"], a["id"]))
    assert r.status_code == 200
    itens = r.json()
    assert [i["conta"]["nome"] for i in itens] == ["Conta Y", "Conta X"]
    assert itens[0]["heroi"]["nome"] == "Heroi A"
    assert [m["poder"] for m in itens[0]["medicoes"]] == [200]
    assert [m["poder"] for m in itens[1]["medicoes"]] == [100]
    assert itens[1]["conta"]["criada_em"] == "2022-08-11"
    assert itens[1]["conta"]["criada_em_aproximada"] == 1


def test_ordem_e_tier(cliente):
    x, _, a, _ = cenario(cliente)
    criar(cliente, "medicoes", conta_id=x["id"], heroi_id=a["id"], data="2026-10-08", arvore=61)
    criar(cliente, "medicoes", conta_id=x["id"], heroi_id=a["id"], data="2026-01-05", arvore=15)
    item = comparar(cliente, (x["id"], a["id"])).json()[0]
    assert item["medicoes"][0]["data"] == "2026-01-05"
    assert item["medicoes"][0]["arvore_tier"] is None
    assert item["medicoes"][1]["arvore_tier"] == "T3"
    assert item["ultima"]["data"] == "2026-10-08"
    assert item["ultima"]["arvore_tier"] == "T3"


def test_ultimo_numero_pula_vazios(cliente):
    x, _, a, _ = cenario(cliente)
    criar(cliente, "medicoes", conta_id=x["id"], heroi_id=a["id"], data="2026-10-08", poder=100)
    criar(cliente, "medicoes", conta_id=x["id"], heroi_id=a["id"], data="2026-10-17", arvore=37)
    item = comparar(cliente, (x["id"], a["id"])).json()[0]
    assert item["ultima"]["data"] == "2026-10-17"
    assert item["ultimo_numero"]["poder"] == {"valor": 100, "data": "2026-10-08"}
    assert item["ultimo_numero"]["armadura"] is None
    assert set(item["ultimo_numero"]) == {"poder", "ataque", "hp", "armadura", "velocidade"}


def test_par_sem_medicoes(cliente):
    x, _, a, _ = cenario(cliente)
    item = comparar(cliente, (x["id"], a["id"])).json()[0]
    assert item["medicoes"] == []
    assert item["ultima"] is None
    assert all(v is None for v in item["ultimo_numero"].values())
    assert item["casinhas"] == []


def test_casinhas_do_proprietario(cliente):
    x, y, a, b = cenario(cliente)
    criar(cliente, "casinhas", conta_id=x["id"], proprietario_id=a["id"], inquilino_id=b["id"],
          nivel=93, transferencia_pct=89.1)
    criar(cliente, "casinhas", conta_id=x["id"], proprietario_id=b["id"], nivel=10)
    itens = comparar(cliente, (x["id"], a["id"]), (y["id"], a["id"])).json()
    assert len(itens[0]["casinhas"]) == 1
    assert itens[0]["casinhas"][0]["inquilino"] == "Heroi B"
    assert itens[0]["casinhas"][0]["nivel"] == 93
    assert itens[1]["casinhas"] == []


def test_erros(cliente):
    cenario(cliente)
    assert cliente.get("/api/comparacao", params={"pares": "abc"}).status_code == 400
    assert cliente.get("/api/comparacao", params={"pares": ""}).status_code == 400
    assert cliente.get("/api/comparacao", params={"pares": "999:1"}).status_code == 404
    assert cliente.get("/api/comparacao", params={"pares": "1:999"}).status_code == 404

"""Testes do endpoint de sessão (dados inventados)."""


def criar(c, tabela, **dados):
    r = c.post(f"/api/{tabela}", json=dados)
    assert r.status_code == 201, r.text
    return r.json()


def cenario(c):
    conta = criar(c, "contas", nome="Conta X")
    a = criar(c, "herois", nome="Heroi A")
    b = criar(c, "herois", nome="Heroi B")
    return conta, a, b


def sessao(c, conta, herois, data="2026-10-17"):
    return c.post("/api/sessao", json={"conta_id": conta["id"], "data": data, "herois": herois})


def medicoes(c):
    return c.get("/api/medicoes").json()


def test_cria_varias(cliente):
    conta, a, b = cenario(cliente)
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 10}, {"heroi_id": b["id"], "poder": 20}])
    assert r.status_code == 200, r.text
    assert len(r.json()["criadas"]) == 2
    assert r.json()["atualizadas"] == []
    linhas = medicoes(cliente)
    assert len(linhas) == 2
    assert {m["data"] for m in linhas} == {"2026-10-17"}


def test_mesmo_dia_atualiza(cliente):
    conta, a, _ = cenario(cliente)
    sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 100, "arvore": 30}])
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "arvore": 37}])
    assert len(r.json()["atualizadas"]) == 1
    linhas = medicoes(cliente)
    assert len(linhas) == 1
    assert linhas[0]["arvore"] == 37
    assert linhas[0]["poder"] == 100


def test_null_limpa(cliente):
    conta, a, _ = cenario(cliente)
    sessao(cliente, conta, [{"heroi_id": a["id"], "artefato": "X"}])
    sessao(cliente, conta, [{"heroi_id": a["id"], "artefato": None}])
    assert medicoes(cliente)[0]["artefato"] is None


def test_vazio_vira_null(cliente):
    conta, a, _ = cenario(cliente)
    sessao(cliente, conta, [{"heroi_id": a["id"], "artefato": ""}])
    assert medicoes(cliente)[0]["artefato"] is None


def test_atualiza_medicao_vinda_da_api_generica(cliente):
    conta, a, _ = cenario(cliente)
    criar(cliente, "medicoes", conta_id=conta["id"], heroi_id=a["id"], data="2026-10-17", poder=5)
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "arvore": 20}])
    assert len(r.json()["atualizadas"]) == 1 and r.json()["criadas"] == []
    linhas = medicoes(cliente)
    assert len(linhas) == 1 and linhas[0]["poder"] == 5 and linhas[0]["arvore"] == 20


def test_tudo_ou_nada(cliente):
    conta, a, _ = cenario(cliente)
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 1}, {"heroi_id": 999, "poder": 2}])
    assert r.status_code == 400
    assert medicoes(cliente) == []


def test_tudo_ou_nada_no_update(cliente):
    conta, a, _ = cenario(cliente)
    sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 1}])
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 2}, {"heroi_id": 999}])
    assert r.status_code == 400
    assert medicoes(cliente)[0]["poder"] == 1


def test_conta_inexistente(cliente):
    _, a, _ = cenario(cliente)
    r = sessao(cliente, {"id": 999}, [{"heroi_id": a["id"]}])
    assert r.status_code == 400
    assert medicoes(cliente) == []


def test_campo_desconhecido(cliente):
    conta, a, _ = cenario(cliente)
    r = sessao(cliente, conta, [{"heroi_id": a["id"], "xyz": 1}])
    assert r.status_code == 400
    assert medicoes(cliente) == []


def test_herois_vazio(cliente):
    conta, _, _ = cenario(cliente)
    assert sessao(cliente, conta, []).status_code == 400


def test_conta_e_data_dentro_do_item_sao_rejeitadas(cliente):
    conta, a, _ = cenario(cliente)
    for extra in ({"data": "2026-10-10"}, {"conta_id": conta["id"]}):
        r = sessao(cliente, conta, [{"heroi_id": a["id"], "poder": 5, **extra}])
        assert r.status_code == 400
    assert medicoes(cliente) == []

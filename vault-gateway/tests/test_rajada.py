from vault_gateway.rajada import Rajada


def test_rajada_dispara_uma_vez_por_janela():
    r = Rajada()
    disparos = [r.contar(t) for t in range(21)]
    assert disparos.count(True) == 1 and disparos[20] is True
    assert not any(r.contar(100 + t) for t in range(30))  # mesma janela
    assert any(r.contar(700 + t) for t in range(21))  # janela nova


def test_vinte_tentativas_nao_disparam():
    r = Rajada()
    assert not any(r.contar(t) for t in range(20))


def test_tentativas_espalhadas_nao_disparam():
    r = Rajada()
    assert not any(r.contar(t * 100) for t in range(100))  # 1 a cada 100 s


def test_contador_do_dia():
    r = Rajada()
    for t in range(5):
        r.contar(t)
    assert r.total_do_dia() == 5
    r.zerar_dia()
    assert r.total_do_dia() == 0


def test_na_janela_conta_so_a_janela_atual():
    r = Rajada()
    for t in range(5):
        r.contar(t)
    assert r.na_janela() == 5
    r.contar(700)
    assert r.na_janela() == 1

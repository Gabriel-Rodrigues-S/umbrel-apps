from alertas.identidade import gateway_de_rota, gateway_do_conteiner, usuario_confiavel

ROTA = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "eth0\t00000000\t0100150A\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    "eth0\t0000150A\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
)


# --- teste do brief ---

def test_cabecalho_forjado_por_outro_conteiner_e_recusado():
    assert not usuario_confiavel("10.21.0.7", {"Tailscale-User-Login": "g@x"}, "g@x", ip_host="10.21.0.1")
    assert usuario_confiavel("10.21.0.1", {"Tailscale-User-Login": "g@x"}, "g@x", ip_host="10.21.0.1")
    assert not usuario_confiavel("10.21.0.1", {"Tailscale-User-Login": "outro@x"}, "g@x", ip_host="10.21.0.1")
    assert not usuario_confiavel("10.21.0.1", {}, "g@x", ip_host="10.21.0.1")


# --- extras ---

def test_cabecalho_sem_diferenca_de_maiusculas():
    assert usuario_confiavel("10.21.0.1", {"tailscale-user-login": "g@x"}, "g@x", ip_host="10.21.0.1")


def test_falha_fechada_sem_configuracao():
    cab = {"Tailscale-User-Login": "g@x"}
    assert not usuario_confiavel("10.21.0.1", cab, "", ip_host="10.21.0.1")
    assert not usuario_confiavel("10.21.0.1", cab, None, ip_host="10.21.0.1")
    assert not usuario_confiavel("10.21.0.1", cab, "g@x", ip_host="")
    assert not usuario_confiavel("10.21.0.1", cab, "g@x", ip_host=None)
    assert not usuario_confiavel(None, cab, "g@x", ip_host="10.21.0.1")
    assert not usuario_confiavel("", {"Tailscale-User-Login": ""}, "", ip_host="")


def test_comparacao_exata():
    assert not usuario_confiavel("10.21.0.1", {"Tailscale-User-Login": "G@x"}, "g@x", ip_host="10.21.0.1")
    assert not usuario_confiavel("10.21.0.1", {"Tailscale-User-Login": " g@x"}, "g@x", ip_host="10.21.0.1")


def test_cabecalho_repetido_e_recusado():
    cab = [("Tailscale-User-Login", "g@x"), ("tailscale-user-login", "outro@x")]
    assert not usuario_confiavel("10.21.0.1", cab, "g@x", ip_host="10.21.0.1")


def test_rota_padrao():
    assert gateway_de_rota(ROTA) == "10.21.0.1"


def test_rota_sem_padrao():
    assert gateway_de_rota(ROTA.splitlines()[0] + "\n" + ROTA.splitlines()[2]) is None
    assert gateway_de_rota("") is None
    assert gateway_de_rota("lixo\nsem formato\n") is None


def test_gateway_do_conteiner_arquivo(tmp_path):
    arq = tmp_path / "route"
    arq.write_text(ROTA)
    assert gateway_do_conteiner(arq) == "10.21.0.1"
    assert gateway_do_conteiner(tmp_path / "nao-existe") is None

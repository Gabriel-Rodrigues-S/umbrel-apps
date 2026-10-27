"""Identidade do Tailscale: o cabeçalho só vale se o pedido vier do host.

O Tailscale Serve roda no host e repassa para 127.0.0.1:8445; o Docker entrega
esse pedido ao contêiner com origem no gateway da rede (o host). Outros
contêineres da mesma rede chegam direto, com o próprio IP, e podem forjar o
cabeçalho: por isso o IP de origem tem de ser exatamente o gateway.
"""
import ipaddress
from pathlib import Path

CABECALHO = "tailscale-user-login"


def gateway_de_rota(texto: str) -> str | None:
    """Extrai o gateway da rota padrão (destino 00000000) do formato de /proc/net/route."""
    for linha in texto.splitlines()[1:]:
        campos = linha.split()
        if len(campos) < 3 or campos[1] != "00000000":
            continue
        try:
            bruto = bytes.fromhex(campos[2])
        except ValueError:
            continue
        if len(bruto) != 4 or bruto == b"\0\0\0\0":
            continue
        return str(ipaddress.IPv4Address(bruto[::-1]))  # hexadecimal little-endian
    return None


def gateway_do_conteiner(arquivo: Path | str = "/proc/net/route") -> str | None:
    """Gateway padrão do contêiner (= host). None se não der para saber (falha fechada)."""
    try:
        return gateway_de_rota(Path(arquivo).read_text(encoding="ascii", errors="replace"))
    except OSError:
        return None


def _valores(cabecalhos, nome: str) -> list[str]:
    itens = cabecalhos.items() if hasattr(cabecalhos, "items") else cabecalhos
    return [v for k, v in itens if isinstance(k, str) and k.lower() == nome]


def usuario_confiavel(ip_origem: str | None, cabecalhos, usuario_permitido: str | None,
                      ip_host: str | None) -> bool:
    """True só se o pedido vem do host e traz exatamente o login permitido."""
    if not usuario_permitido or not ip_host or not ip_origem:
        return False
    if ip_origem != ip_host:
        return False
    valores = _valores(cabecalhos, CABECALHO)
    return len(valores) == 1 and valores[0] == usuario_permitido

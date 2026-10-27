import pytest


@pytest.fixture
def vault(tmp_path):
    """Árvore de exemplo: raiz em tmp_path/vault, 'fora' ao lado."""
    raiz = tmp_path / "vault"
    (raiz / "Referências").mkdir(parents=True)
    (raiz / "Referências" / "Nota com acento.md").write_text("# Nota\ncorpo\n")
    (raiz / "Pasta").mkdir()
    (raiz / "Pasta" / "b.txt").write_text("b")
    (raiz / ".obsidian").mkdir()
    (raiz / ".obsidian" / "x.json").write_text("{}")
    (raiz / ".git").mkdir()
    (raiz / ".git" / "config").write_text("[core]")
    (raiz / "a.pdf").write_bytes(b"%PDF")
    # fora do vault
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.md").write_text("segredo")
    (tmp_path / "fora.md").write_text("fora")
    (raiz / "link-para-fora").symlink_to(fora, target_is_directory=True)
    (raiz / "link-arquivo-fora.md").symlink_to(tmp_path / "fora.md")
    # links internos
    (raiz / "atalho.md").symlink_to(raiz / "Referências" / "Nota com acento.md")
    (raiz / "atalho-obsidian.json").symlink_to(raiz / ".obsidian" / "x.json")
    return raiz


class _ServidorFalso:
    """Alertas falso: falha (ConnectError) até .ligar(), depois responde 201."""

    def __init__(self):
        import httpx

        self.url = "http://alertas.teste"
        self.ligado = False
        self.recebidos = []
        self.cliente = httpx.Client(transport=httpx.MockTransport(self._tratar))

    def _tratar(self, request):
        import httpx

        if not self.ligado:
            raise httpx.ConnectError("fora do ar", request=request)
        self.recebidos.append(request)
        return httpx.Response(201, json={"ok": True})

    def ligar(self):
        self.ligado = True


@pytest.fixture
def servidor_falso():
    return _ServidorFalso()

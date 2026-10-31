# inbox-pc

Coletor da **Inbox do Chat**. Roda no PC (não vira imagem): a cada 15 minutos
copia as notas novas que o Chat criou no servidor (pasta de espera do
vault-gateway) para `Inbox/` do vault do PC. O Obsidian Sync leva o resto.

Só usa a biblioteca padrão do Python 3.12. O servidor é tratado como não
confiável.

## Instalação

```bash
mkdir -p ~/.local/share/coleta-inbox ~/.config/coleta-inbox ~/.config/systemd/user
cp coleta.py ~/.local/share/coleta-inbox/
cp coleta-inbox.service coleta-inbox.timer ~/.config/systemd/user/
```

Config (`~/.config/coleta-inbox/config.json`; valores só no PC, nunca no
repositório). Use o mesmo `ssh_host` da conferência; `caminho_remoto` é a
pasta de espera, com `/data/inbox` no fim do diretório do app:

```json
{
  "ssh_host": "umbrel@umbrel.local",
  "caminho_remoto": "/home/umbrel/umbrel/app-data/garod004-apps-vault-gateway/data/inbox",
  "caminho_local": "<pasta do vault no PC>"
}
```

Ativar:

```bash
systemctl --user daemon-reload
systemctl --user enable --now coleta-inbox.timer
journalctl --user -u coleta-inbox.service   # ver registros
```

Estado: `~/.local/state/coleta-inbox/coletados.json`.

## O que faz

1. Lista a pasta de espera por `ssh` (`find` + `sha256sum`, só leitura).
2. Para cada arquivo ainda não coletado (mesmo nome **e** mesmo sha256), baixa
   no máximo 100 KiB, confere o sha256 e o conteúdo (texto UTF-8, não vazio,
   sem NUL) e o nome (mesmas regras do gateway).
3. Grava em `Inbox/` com criação exclusiva. Se o nome já existir (ignorando
   caixa e acentuação decomposta), grava `Nome-2.md`, `Nome-3.md`...
4. Registra no estado o que coletou; por isso não recopia, mesmo que você
   apague ou mova a nota. Entradas de notas que sumiram do servidor
   (limpeza de 30 dias) saem do estado.
5. No máximo 20 notas por execução. Cada nota gravada ou ignorada vira uma
   linha no journal, só com o nome.

Servidor inacessível: registra e sai com 0, sem tocar o estado. Config ausente
ou inválida, ou comando remoto que falha: mensagem no stderr e saída 1.

## O que nunca faz

- Nunca sobrescreve nem apaga nota do vault (nem remove nada do servidor).
- Nunca grava fora de `Inbox/`; se `Inbox` for link simbólico, não grava.
- Nunca executa nada vindo do servidor; ignora nomes fora das regras
  (`../x.md`, `a/b.md`, `.oculto.md`, `x.txt`...), arquivos maiores que
  102 400 bytes, binários ou com sha256 diferente do listado.

## Testes

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

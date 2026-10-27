# conferencia-pc

Camada 4 da proteção do vault. Roda no PC (não vira imagem): a cada 15 minutos
compara os SHA-256 do vault local com a cópia somente leitura do Umbrel (via
`ssh`). Se a **mesma** divergência persistir em 2 execuções seguidas, envia um
aviso `normal` ("Cópias do vault divergentes") ao app de alertas. Se o Umbrel
estiver inacessível, só registra no journal; não alerta e não altera o estado.

Só usa a biblioteca padrão do Python 3.12.

## Instalação (feita na Tarefa 13)

```bash
mkdir -p ~/.local/share/conferencia-vault ~/.config/conferencia-vault \
         ~/.config/systemd/user
cp conferencia.py ~/.local/share/conferencia-vault/
cp conferencia-vault.service conferencia-vault.timer ~/.config/systemd/user/
```

Config (`~/.config/conferencia-vault/config.json`; valores só no PC, nunca no
repositório):

```json
{
  "ssh_host": "<host ssh do Umbrel, com chave>",
  "caminho_remoto": "<pasta do vault no Umbrel>",
  "caminho_local": "<pasta do vault no PC>",
  "url_alertas": "<URL do endpoint de alertas>"
}
```

Token do remetente `conferencia-pc` (uma linha) e permissões:

```bash
install -m 600 /dev/null ~/.config/conferencia-vault/token
# colar o token no arquivo
chmod 600 ~/.config/conferencia-vault/token ~/.config/conferencia-vault/config.json
```

O script recusa rodar (código 2) se o token for legível por grupo/outros.

Ativar:

```bash
systemctl --user daemon-reload
systemctl --user enable --now conferencia-vault.timer
journalctl --user -u conferencia-vault.service   # ver registros
```

Estado: `~/.local/state/conferencia-vault/estado.json`.

## Testes

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

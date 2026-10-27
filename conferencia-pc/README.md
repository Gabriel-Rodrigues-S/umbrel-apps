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
  "url_alertas": "<URL do endpoint de alertas>",
  "ignorar": ["*.py", "Anexos/*.html"]
}
```

### O que é comparado

- Qualquer caminho com um componente começando por `.` é ignorado **nos dois
  lados** (`.obsidian/`, `.git/`, `.trash/`, `.gitignore`, `pasta/.oculto.md`...):
  o Obsidian Sync nunca sincroniza arquivos e pastas ocultos, então eles
  sempre divergiriam.
- `ignorar` (opcional): lista de globs `fnmatch` aplicados ao caminho relativo
  (separador `/`), também nos dois lados. Atenção: no `fnmatch` o `*` também
  casa com `/` (`*.py` pega `.py` em qualquer pasta).
- O Sync só leva ao Umbrel os tipos de arquivo ligados em **Configurações →
  Sincronização → "Other file types"** (e imagens, áudio, vídeo, PDF conforme
  as opções). Se "other file types" estiver desligado, `.py`, `.json`, `.csv`,
  `.html` etc. ficam só no PC: inclua esses padrões em `ignorar` (ex.:
  `["*.py", "*.json", "*.csv", "*.html"]`), senão a divergência é permanente e
  qualquer mudança passageira volta a gerar alerta.

Os avisos respeitam os limites do app de alertas: título até 120 caracteres,
detalhes até ~19000 (com "… (cortado)") e corpo abaixo de 64 KiB.

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

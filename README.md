# umbrel-apps

Monorepo com apps self-hosted para o servidor Umbrel. Todos os apps são construídos com FastAPI + SQLite + Docker e publicados automaticamente no GitHub Container Registry via GitHub Actions.

---

## Apps disponíveis

### 🎬 Video Downloader
Interface web para baixar vídeos e músicas de qualquer plataforma.

- Suporta YouTube, Twitter/X, Instagram, TikTok e centenas de outros sites via [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Download de vídeos em 1080p, 720p e 480p (MP4)
- Download de áudio em MP3 (192kbps)
- Suporte a playlists completas
- Progresso em tempo real e histórico de downloads

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/yt-downloader:latest`
**Porta:** 8090

---

### 🔄 File Converter
Conversor de arquivos local para toda a família usar sem depender de serviços externos.

- **Vídeo:** MP4 ↔ MKV, MP4 → AVI, qualquer vídeo → MP3
- **Áudio:** MP3 ↔ WAV, FLAC → MP3, qualquer áudio → FLAC
- **Imagem:** PNG ↔ JPG, WEBP ↔ PNG/JPG, imagem → PDF
- **Documento:** PDF → DOCX, DOCX/PPTX/XLSX → PDF, PDF → PNG por página (ZIP)
- Progresso em tempo real e histórico de conversões

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/file-converter:latest`
**Porta:** 9191

---

### 📈 Painel Mercado
Agregador de notícias e cotações do mercado financeiro, atualizado em segundo plano.

- Notícias reais via RSS: InfoMoney, Investing.com (Brasil e global), Cointelegraph Brasil, CNBC, TradingView Brasil, Livecoins, Invezz e BeInCrypto Brasil
- Categorização automática por palavras-chave (Ações & B3, Câmbio, Juros & BC, Cripto, Commodities, Mercados globais)
- Cotações ao vivo via Yahoo Finance: Ibovespa, S&P 500, Nasdaq, USD/BRL, EUR/USD, Bitcoin, Ethereum, petróleo (WTI) e ouro
- Selic e PTAX via API pública do Banco Central do Brasil
- Cache em disco: se uma fonte cair, o painel mantém o último dado bom em vez de ficar vazio

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/painel-mercado:latest`
**Porta:** 8420

---

### 📊 Radar Quant
Radar estatístico de ações e cripto, com gráficos e recomendações baseadas em evidência.

- Busca em todo o catálogo da B3 e dos EUA (e cripto): qualquer papel pode ser aberto sob demanda e adicionado à watchlist
- Gráficos interativos em doze intervalos (1m a 1A, com intraday sob demanda; cotação de ações pode vir com atraso)
- Score por ativo calculado a partir de indicadores estatísticos, sempre acompanhado da evidência que o sustenta
- Setups de curto prazo (swing) e notícias por ativo
- Screener pré-analisado dos índices IBrA, Ibovespa, S&P 500 e Nasdaq-100, com filtros e resumo do índice
- Ranking dos ativos monitorados e sugestão de carteira
- Análises apenas informativas: não é recomendação profissional de investimento

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/radar-quant:latest`
**Porta:** 8430

---

### ⛏️ Terraria
Servidor dedicado oficial do Terraria (vanilla) sempre ligado, com painel de controle.

- Servidor baixado de terraria.org no build da imagem (versão em `terraria/Dockerfile`, `ARG TERRARIA_VERSAO`)
- Jogo na porta **7777** publicada direto no host (o app_proxy só serve HTTP); entrar pelo IP do Umbrel no Tailscale
- Backup automático do mundo a cada 6 h e sempre que o app é desligado/atualizado; baixar e restaurar pelo painel
- Enviar/trocar mundo (.wld), salvar na hora, console de comandos

**Atualizar o Terraria:** trocar `TERRARIA_VERSAO` no `terraria/Dockerfile` → subir `version` em
`garod004-apps-terraria/umbrel-app.yml` → push (o CI publica a tag) → apontar o `image:` do compose para a
tag nova → push → clicar **Atualizar** uma vez no Umbrel. Os mundos ficam em `${APP_DATA_DIR}/data` e não são apagados.

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/terraria:latest`
**Portas:** 7878 (painel) e 7777 (jogo)

---

### 🔐 Gateway do Vault
Acesso somente leitura, por conector MCP, a uma cópia de notas mantida no servidor.

- Quatro ferramentas de consulta: listar, ler, buscar e recentes
- Quinta ferramenta, `criar_nota` (Inbox): só cria notas novas numa pasta de espera; o vault continua somente leitura
- Token por cliente, revogável sem reiniciar; log de auditoria de cada acesso
- Três serviços: gateway, histórico de alterações e sincronização (modo só download, configurada uma vez por terminal)
- Publicado só no loopback do host em **127.0.0.1:8441** (exceção documentada; a 8440 do loopback é do umbreld). O Tailscale Funnel/Serve aponta para `http://127.0.0.1:8441`; o vault é montado `:ro` no gateway e no histórico
- Avisa o app Alertas sobre tentativas negadas e divergências

**Configuração depois de instalar** (valores reais só no volume do app, nunca neste repositório):
- Sincronização: além do `--mode pull-only --conflict-strategy merge` que o contêiner mostra, use
  `ob sync-config --file-types image,audio,video,pdf,unsupported` se o cofre tiver arquivos que não são notas
  (`.py`, `.json`, `.docx`...). Sem `unsupported` eles não chegam ao servidor.
- `config/avisos.json` (permissão 600):
  ```json
  {
    "url": "http://garod004-apps-alertas_server_1:8445/api/alertas",
    "tokens": {"gateway": "<token do remetente gateway>", "historico": "<token do remetente historico>"},
    "deteccao": {"modo": "B", "download": "^(?:Downloaded|Deleting) (?P<caminho>.+)$"}
  }
  ```
  O `ob` não registra envios no log, então a detecção usa o **modo B**: toda mudança no cofre precisa ter um
  `Downloaded` ou `Deleting` correspondente no `sync.log`. Sem o `Deleting`, apagar uma nota em outro aparelho
  gera um alerta grave falso. Depois de editar, reinicie o serviço `historico`.
- Exposição: o conector personalizado do Claude só alcançou o gateway pelo Funnel na porta **443**
  (`tailscale funnel --bg --https=443 http://127.0.0.1:8441`); na 10000 ele não conectava. No formulário do
  conector, desligue o login (OAuth) e use o cabeçalho `Authorization: Bearer <token>`.
- Inbox (`criar_nota`): crie `config/inbox.json` (permissão 600) com `{"clientes": ["claude"]}`. Sem o arquivo, ou se
  estiver ilegível ou malformado, ninguém escreve; cliente fora da lista recebe `sem_permissao`.
  Regras: só nota nova (nunca sobrescreve, nem com outra caixa ou acentuação decomposta), texto UTF-8 de até
  100 KB, no máximo 5 notas a cada 24 h, e arquivos com mais de 30 dias são limpos da espera. Toda negada gera
  alerta grave e todo sucesso, alerta normal; o conteúdo da nota nunca vai para log nem alerta.
  As notas ficam na pasta de espera `data/inbox/` do app (fora do vault); quem leva para o vault é o coletor no PC,
  descrito em [`inbox-pc/README.md`](inbox-pc/README.md).

**Imagens Docker:** `ghcr.io/gabriel-rodrigues-s/vault-gateway` e `ghcr.io/gabriel-rodrigues-s/vault-sync`
**Porta:** 8440

---

### 🔔 Alertas
Central de alertas dos apps do servidor, com notificação push genérica.

- Cada remetente autorizado usa um token próprio; histórico guardado por 365 dias
- Gravidades grave, normal e informativa (a informativa nunca gera push)
- Push sempre genérico ("Novo alerta no servidor"); detalhes só dentro do app
- PWA instalável; publicado só no loopback do host em **127.0.0.1:8446** (exceção documentada; a 8445 do loopback é do umbreld). O Tailscale Serve aponta para `http://127.0.0.1:8446`

**Imagem Docker:** `ghcr.io/gabriel-rodrigues-s/alertas:latest`
**Porta:** 8445

---

## Estrutura do repositório

```
umbrel-apps/
├── app/                              # Código-fonte — Video Downloader
│   ├── main.py
│   ├── downloader.py
│   ├── database.py
│   └── templates/index.html
├── file-converter/                   # Código-fonte — File Converter
│   ├── app/
│   │   ├── main.py
│   │   ├── converter.py
│   │   ├── database.py
│   │   └── templates/index.html
│   ├── Dockerfile
│   └── requirements.txt
├── garod004-apps-video-downloader/      # Manifests Umbrel — Video Downloader
│   ├── docker-compose.yml
│   ├── umbrel-app.yml
│   └── icon.svg
├── garod004-apps-file-converter/     # Manifests Umbrel — File Converter
│   ├── docker-compose.yml
│   ├── umbrel-app.yml
│   └── icon.svg
├── umbrel-app-store.yml              # Manifest da loja de apps
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/docker-publish.yml
```

## Stack técnica

- **Backend:** Python 3.12 + FastAPI
- **Banco de dados:** SQLite
- **Frontend:** HTML + CSS + Vanilla JS (sem frameworks)
- **Deploy:** Docker + GitHub Actions → ghcr.io
- **Servidor:** [Umbrel](https://umbrel.com)

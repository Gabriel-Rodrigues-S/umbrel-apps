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

**Imagem Docker:** `ghcr.io/garod004/yt-downloader:latest`
**Porta:** 8090

---

### 🔄 File Converter
Conversor de arquivos local para toda a família usar sem depender de serviços externos.

- **Vídeo:** MP4 ↔ MKV, MP4 → AVI, qualquer vídeo → MP3
- **Áudio:** MP3 ↔ WAV, FLAC → MP3, qualquer áudio → FLAC
- **Imagem:** PNG ↔ JPG, WEBP ↔ PNG/JPG, imagem → PDF
- **Documento:** PDF → DOCX, DOCX/PPTX/XLSX → PDF, PDF → PNG por página (ZIP)
- Progresso em tempo real e histórico de conversões

**Imagem Docker:** `ghcr.io/garod004/file-converter:latest`
**Porta:** 9191

---

### 📈 Painel Mercado
Agregador de notícias e cotações do mercado financeiro, atualizado em segundo plano.

- Notícias reais via RSS: InfoMoney, Investing.com, Cointelegraph Brasil, CNBC, TradingView Brasil, Livecoins, Invezz e BeInCrypto Brasil
- Categorização automática por palavras-chave (Ações & B3, Câmbio, Juros & BC, Cripto, Commodities, Mercados globais)
- Cotações ao vivo via Yahoo Finance: Ibovespa, S&P 500, Nasdaq, USD/BRL, EUR/USD, Bitcoin, Ethereum, petróleo (WTI) e ouro
- Selic e PTAX via API pública do Banco Central do Brasil
- Cache em disco: se uma fonte cair, o painel mantém o último dado bom em vez de ficar vazio

**Imagem Docker:** `ghcr.io/garod004/painel-mercado:latest`
**Porta:** 8420

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

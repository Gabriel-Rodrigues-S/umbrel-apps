# E2E

Roteiro de ponta a ponta com o [agent-browser](https://github.com/vercel-labs/agent-browser).

```bash
npm i -g agent-browser && agent-browser install   # uma vez
e2e/run.sh                          # sobe o backend com dados sintéticos e testa
e2e/run.sh http://127.0.0.1:8430    # testa um servidor já no ar (ex.: contêiner)
```

Sai com código diferente de zero se alguma verificação falhar. Os screenshots
ficam em `e2e/out/` (ignorado pelo git).

Contra um servidor real o roteiro adiciona e remove `TSLA` da watchlist.

# Runbook de Release e Rollback

## Pré-release
1. Confirmar pipeline verde em pull request.
2. Validar smoke check de release no branch alvo.
3. Confirmar janela de deploy de baixo risco.
4. Publicar nota de release com mudanças e riscos.

## Passo a passo de release
1. Merge na branch principal.
2. Aguardar jobs de quality + frontend/e2e + release-readiness.
3. Executar smoke funcional pós-deploy:
   - Login
   - Dashboard
   - Endpoint de health do tema
4. Monitorar erros e latência por 30 minutos.

## Critérios de rollback
- Aumento de erros HTTP 5xx acima de 2% por 5 minutos.
- Endpoint de health indisponível por mais de 2 minutos.
- Fluxo crítico de login indisponível.

## Rollback operacional
1. Reverter commit de release:
   - `git revert <commit>`
2. Reaplicar artefato anterior no ambiente.
3. Rodar smoke check novamente.
4. Comunicar status e causa raiz.

## Pós-incidente
1. Abrir RCA em até 24h.
2. Criar teste de regressão obrigatório.
3. Atualizar este runbook com aprendizado.

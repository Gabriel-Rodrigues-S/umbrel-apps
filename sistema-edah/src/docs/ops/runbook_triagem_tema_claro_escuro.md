# Runbook Curto de Triagem - Tema Claro/Escuro

## Objetivo
Padronizar a triagem de incidentes de tema (light/dark) para reduzir tempo de diagnostico, restaurar experiencia visual rapidamente e evitar regressao recorrente.

## Escopo
1. Falhas de persistencia de tema entre paginas.
2. Inconsistencia visual de sidebar/header no dark.
3. Regressao de contraste/foco em componentes principais.

## Sinais de alerta
1. Tema retorna para light apos navegar pelo menu.
2. Sidebar renderiza cor clara em dark mode.
3. E2E de tema ou baseline visual falha em CI.

## Triage inicial (ate 10 min)
1. Reproduzir com usuario autenticado em duas rotas: dashboard e configuracoes.
2. Validar estado do tema no carregamento inicial e apos troca de rota.
3. Executar testes dedicados:
   - npm run test:e2e:theme
   - npm run test:e2e:baseline
4. Classificar severidade:
   - SEV1: quebra geral de navegacao por tema.
   - SEV2: inconsistencia visual relevante sem indisponibilidade.
   - SEV3: defeito localizado com workaround.

## Diagnostico tecnico orientado por camada
1. Frontend (tokens/CSS): verificar variaveis de tema e seletores da sidebar/header.
2. Bootstrap da pagina: confirmar reaplicacao de tema no carregamento.
3. Backend/sessao: validar fonte de verdade da preferencia de tema do usuario.
4. Testes: confirmar se falha e funcional, visual ou ambiente.

## Mitigacao rapida
1. Se regressao apos release: executar rollback conforme runbook de release.
2. Se impacto parcial: aplicar hotfix de token/selector com PR curto e gate obrigatorio.
3. Se flakiness visual: rerun controlado e registrar variacao de ambiente antes de aprovar.

## Criterios de saida do incidente
1. Teste funcional de tema verde (5/5 ou superior no pacote atual).
2. Baseline visual executado sem falha para telas prioritarias.
3. Validacao manual em desktop e mobile nas rotas criticas.
4. Comunicacao de encerramento com causa raiz e acao preventiva.

## Evidencias minimas obrigatorias
1. Link do pipeline/execucao com gate de tema verde.
2. Hash/PR do hotfix ou rollback aplicado.
3. Registro de causa raiz e medida preventiva no relatorio de execucao.

## Responsabilidades
1. QA: reproducao, evidencias e validacao final.
2. Fullstack: diagnostico de persistencia e correcao ponta a ponta.
3. DevOps/Infra: garantia de gate bloqueante e suporte de rollback.

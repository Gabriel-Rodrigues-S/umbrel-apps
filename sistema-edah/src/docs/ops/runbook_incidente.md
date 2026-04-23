# Runbook de Resposta a Incidente

## Severidade
- SEV1: indisponibilidade total de fluxo crítico.
- SEV2: degradação relevante com impacto ao usuário.
- SEV3: impacto parcial sem bloqueio de operação.

## Triage inicial (até 10 min)
1. Confirmar sintoma e escopo.
2. Checar status do endpoint de health.
3. Verificar últimos deploys e alterações recentes.
4. Definir severidade e acionar responsáveis.

## Mitigação
1. Aplicar rollback se houver regressão pós-release.
2. Isolar funcionalidade com falha (feature toggle/manual fallback).
3. Restaurar serviço prioritário ao menor tempo possível.

## Comunicação
1. Atualização inicial em até 15 min.
2. Atualização periódica a cada 30 min enquanto incidente aberto.
3. Encerramento com impacto, duração e ação aplicada.

## Pós-incidente
1. RCA com causa raiz e fatores contribuintes.
2. Plano de ação com prazo e responsável.
3. Revisão de monitoramento/alerta para evitar recorrência.

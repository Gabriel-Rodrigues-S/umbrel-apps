# Documentacao Completa do Projeto

## 1. Visao Geral

O projeto e uma aplicacao Django para gestao de igreja, cobrindo cadastro de pessoas, membros, visitantes, familias, liderancas, pequenos grupos, ministerios, discipulado, cursos, eventos, financeiro, comunicacao, relatorios e configuracoes de sistema.

Objetivo principal:
- Centralizar a operacao administrativa e ministerial da igreja em uma interface web unica.

Stack principal:
- Backend: Django 5
- Banco de dados: SQLite
- Frontend: templates Django + Bootstrap 5 + JavaScript
- Componentes de UI: DataTables, Select2, jQuery Mask, Chart.js
- Testes: pytest, pytest-django, pytest-cov

Caracteristicas relevantes:
- Autenticacao com usuario customizado baseado em e-mail
- Preferencia de tema claro/escuro persistida por usuario
- APIs internas para tema e chat
- Estrutura modular por dominio funcional
- Scripts operacionais para smoke, backup e restore

## 2. Objetivo do Artefato

Este documento serve como referencia central do projeto para onboarding, manutencao, handoff tecnico, operacao local e apoio a decisoes de evolucao.

Publico-alvo:
- Desenvolvimento backend e frontend
- QA
- Lideranca tecnica
- Operacao e suporte

## 3. Escopo

Inclui:
- Arquitetura da aplicacao
- Estrutura de pastas
- Modulos funcionais
- Principais rotas e APIs
- Setup local
- Scripts operacionais
- Estrategia de testes e operacao

Exclui:
- Documentacao detalhada de cada model/campo individual
- Manual funcional completo para usuario final
- Processo de deploy de infraestrutura externa alem do que esta refletido no repositorio

## 4. Arquitetura Geral

Arquitetura adotada:
- Monolito Django com organizacao por dominios dentro do app `church`
- Renderizacao server-side com templates Django
- Recursos estaticos centralizados em `static/`
- Persistencia local em SQLite

Fluxo tecnico resumido:
1. O usuario acessa uma rota Django.
2. A view da camada `church/views_app/` processa a regra e prepara o contexto.
3. Formularios em `church/forms/` aplicam validacoes e configuracao visual.
4. Models em `church/models/` representam o dominio e a persistencia.
5. Templates em `templates/app/` renderizam a interface.
6. CSS e JS em `static/` complementam o comportamento da UI.

## 5. Estrutura de Pastas

### Raiz
- `manage.py`: ponto de entrada Django.
- `requirements.txt`: dependencias Python principais.
- `README.md`: guia rapido de uso.
- `db.sqlite3`: banco local quando gerado.
- `docs/`: documentacao do projeto e runbooks operacionais.
- `scripts/`: utilitarios operacionais e geradores auxiliares.

### Aplicacao principal
- `church/`: app principal do dominio.

Subpastas relevantes:
- `church/models/`: modelos por dominio.
- `church/forms/`: formularios e padronizacao de widgets.
- `church/views_app/`: views por area funcional.
- `church/management/commands/`: comandos customizados de bootstrap.
- `church/templatetags/`: tags customizadas de template.

### Configuracao
- `config/settings.py`: configuracoes Django por ambiente.
- `config/urls.py`: roteamento raiz.
- `config/asgi.py` e `config/wsgi.py`: entradas ASGI/WSGI.

### Frontend
- `templates/app/`: templates organizados por modulo.
- `static/css/`: estilos base e tokens de tema.
- `static/js/`: scripts globais da aplicacao.

### Documentacao operacional
- `docs/ops/runbook_release_rollback.md`
- `docs/ops/runbook_incidente.md`
- `docs/ops/backup_continuidade.md`
- `docs/ops/runbook_triagem_tema_claro_escuro.md`

## 6. Configuracao e Ambiente

Arquivo principal de configuracao:
- `config/settings.py`

Pontos importantes:
- `DJANGO_ENV`: define `development` ou `production`
- `DJANGO_DEBUG`: controla debug
- `DJANGO_SECRET_KEY`: obrigatoria em producao com debug desligado
- `DJANGO_ALLOWED_HOSTS`: hosts permitidos
- `DJANGO_CSRF_TRUSTED_ORIGINS`: origens confiaveis para CSRF

Configuracoes relevantes:
- `AUTH_USER_MODEL = "church.User"`
- Banco padrao SQLite em `db.sqlite3`
- Arquivos estaticos em `static/`
- Midia em `uploads/`
- Idioma padrao: `pt-br`
- Fuso horario: `America/Sao_Paulo`

Seguranca em producao:
- `SECURE_SSL_REDIRECT`
- `SESSION_COOKIE_SECURE`
- `CSRF_COOKIE_SECURE`
- HSTS configuravel por variaveis de ambiente

## 7. Setup Local

Pre-requisitos:
- Python compativel com Django 5
- `uv` instalado

Fluxo recomendado:

```bash
cd /home/gabriel/Documentos/django-sis-igreja
uv sync --dev
uv run python manage.py migrate
export BOOTSTRAP_ADMIN_PASSWORD='defina-uma-senha-forte'
uv run python manage.py bootstrap_sys_edah
uv run python manage.py runserver
```

Acesso local:
- Aplicacao: `http://127.0.0.1:8000/`
- Admin Django: `http://127.0.0.1:8000/admin/`

Bootstrap inicial:
- Comando: `uv run python manage.py bootstrap_sys_edah`
- Cria superusuario, registro inicial de igreja e categorias financeiras padrao.

Padrao local em DEBUG:
- Se `BOOTSTRAP_ADMIN_PASSWORD` nao for definida e `DEBUG=True`, o bootstrap usa `admin123`.
- Isso deve ser usado apenas em ambiente local.

## 8. Dominio e Modulos Funcionais

Os modelos sao agregados em `church/models/__init__.py` e distribuidos por dominio.

### 8.1 Usuarios e sistema
- `User`: usuario customizado autenticado por e-mail.
- Niveis de acesso: admin, pastor, lider, secretaria, financeiro, usuario.
- Status de usuario: ativo/inativo.
- Preferencia de tema: `light` ou `dark`.
- `HistoricoAcao`: rastreamento historico do sistema.

### 8.2 Cadastros e pessoas
- `Pessoa`
- `Membro`
- `Visitante`
- `Lider`
- `Funcionario`
- `Familia`, `FamiliaMembro`, `Casal`
- `Igreja`

### 8.3 Ministerios e grupos
- `Ministerio`, `MinisterioMembro`
- `PequenoGrupo`, `PequenoGrupoMembro`

### 8.4 Discipulado e classes
- `Discipulado`
- `ClasseEstudo`
- `ClasseAluno`

### 8.5 Financeiro
- `CategoriaFinanceira`
- `LancamentoFinanceiro`
- Apoio para dizimos, ofertas e relatorios financeiros

### 8.6 Cursos
- `Curso`
- `CursoModulo`
- `CursoAula`
- `CursoMatricula`
- `CursoPresenca`
- `CursoNota`
- `Certificado`

### 8.7 Eventos
- `Evento`
- `EventoResponsavel`
- `EventoInscricao`

### 8.8 Comunicacao
- `Noticia`
- `PedidoOracao`
- `Galeria`, `GaleriaFoto`
- `Mensagem`

## 9. Camada de Views e Rotas

As rotas de aplicacao estao concentradas em `church/urls.py` e expostas pela raiz em `config/urls.py`.

Rotas principais por area:
- Autenticacao: login, logout, perfil
- Igreja: edicao de dados institucionais
- Pessoas: membros, visitantes, lideres, funcionarios
- Familias: familias, membros de familia, casais
- Discipulado: discipulado e classes
- Pequenos grupos e ministerios
- Financeiro: lancamentos, dizimos, ofertas, categorias, relatorios
- Cursos: cursos, modulos, aulas, matriculas, presencas, notas, certificados
- Eventos: eventos, inscricoes, responsaveis
- Comunicacao: noticias, pedidos de oracao, galeria, mensagens
- Relatorios: membros, visitantes, grupos, cursos, eventos
- Configuracoes: usuarios e configuracoes de sistema

Pagina inicial:
- Dashboard autenticado com cards, graficos e atalhos.

## 10. APIs Internas

### 10.1 API de tema
Arquivo:
- `church/views_app/theme_api.py`

Endpoints:
- `GET /api/user/theme/`
- `PATCH /api/user/theme/`
- `GET /api/health/theme/`

Finalidade:
- Persistir preferencia de tema do usuario autenticado
- Retornar tema atual
- Fornecer health check simples

Comportamentos importantes:
- Requer autenticacao para leitura/alteracao da preferencia do usuario
- Valida payload de tema
- Registra falhas de persistencia em log

### 10.2 API de chat
Arquivo:
- `church/views_app/chat_api.py`

Endpoints:
- `GET /api/chat/ping/`
- `GET /api/chat/mensagens/`
- `POST /api/chat/enviar/`

Finalidade:
- Sincronizar contatos com conversa recente
- Buscar mensagens por conversa
- Enviar mensagens entre usuarios

Caracteristicas importantes:
- Requer autenticacao
- Possui rate limit por escopo
- Limita tamanho da mensagem
- Impede envio para o proprio usuario

## 11. Frontend e Experiencia

Tecnologias usadas no frontend:
- Bootstrap 5
- DataTables
- Select2
- Chart.js
- jQuery
- jQuery Mask

Arquivos principais:
- `static/css/style.css`: estilos base e legados
- `static/css/theme-tokens.css`: tokens e compatibilidade com tema claro/escuro
- `static/js/scripts.js`: comportamentos globais, incluindo ThemeManager
- `templates/app/base.html`: layout base, imports, inicializacao de DataTables e bootstrap de tema

Tema claro/escuro:
- Preferencia inicial lida de meta tag do backend ou `localStorage`
- Tema aplicado no `html[data-theme]`
- `color-scheme` sincronizado com o tema
- Ajustes anti-flash implementados para primeira pintura, campos, DataTables e bordas

## 12. Formularios

Os formularios ficam em `church/forms/` e seguem padrao de widgets Bootstrap.

Caracteristicas:
- Uso recorrente de `form-control`, `form-select` e `form-check-input`
- Padronizacao de mascaras e classes por dominio
- Integracao com tema escuro por tokens CSS

## 13. Comandos e Scripts

### Comando Django customizado
- `bootstrap_sys_edah`: cria estrutura inicial minima para uso local

### Scripts utilitarios
- `scripts/smoke_healthcheck.sh`: smoke test de readiness
- `scripts/backup_sqlite.sh`: backup do SQLite
- `scripts/restore_sqlite.sh`: restore do SQLite

### Scripts auxiliares de geracao
- `gen_form_extends.py`
- `gen_simple_templates.py`
- `generate_templates.py`

## 14. Testes e Qualidade

Dependencias de teste:
- `pytest`
- `pytest-django`
- `pytest-cov`

Arquivos identificados:
- `church/tests.py`
- `church/tests_theme_api.py`

Cobertura funcional observada no repositorio atual:
- Testes de API de tema
- Fluxo de preferencia light/dark e validacoes de payload

Comandos uteis:

```bash
uv run pytest
uv run pytest church/tests_theme_api.py
```

Observacao:
- O projeto tambem utiliza validacoes frontend e E2E em fluxos de tema, conforme evidencias operacionais do ciclo, embora o repositorio inspecionado aqui exponha principalmente a camada Python de testes automatizados.

## 15. Operacao e Continuidade

Runbooks existentes:
- `docs/ops/runbook_release_rollback.md`
- `docs/ops/runbook_incidente.md`
- `docs/ops/backup_continuidade.md`
- `docs/ops/runbook_triagem_tema_claro_escuro.md`

Rotina recomendada:
1. Executar smoke apos alteracoes relevantes.
2. Garantir backup do SQLite antes de operacoes sensiveis.
3. Validar tema e fluxos principais em telas com DataTables.
4. Registrar riscos residuais e decisao de release quando houver gate bloqueado.

## 16. Riscos, Premissas e Dependencias

Premissas:
- Projeto pensado para execucao simples local com SQLite.
- Frontend depende de bibliotecas servidas por CDN no template base.
- Documentacao operacional complementar fica em `docs/ops/`.

Riscos tecnicos:
- Dependencia de assets externos via CDN pode impactar ambiente offline ou restrito.
- Uso de SQLite e adequado para desenvolvimento e cenarios simples, mas tem limite operacional para maior concorrencia.
- Parte do CSS legado convive com tokens modernos, exigindo cuidado em alteracoes visuais.

Dependencias funcionais:
- Usuario autenticado para recursos internos de tema e chat.
- Bootstrap inicial para dados minimos de uso.

## 17. Definition of Done da Documentacao

Esta documentacao e considerada pronta porque:
- Descreve arquitetura, setup, modulos, APIs, scripts e operacao
- Explicita escopo e publico-alvo
- Consolida evidencias do que existe no repositorio atual
- Registra riscos e premissas de manutencao
- Funciona como artefato base para onboarding e handoff tecnico

## 18. Proximos Passos Recomendados

1. Criar documentacao complementar por modulo funcional, se o time precisar mais profundidade.
2. Padronizar um indice de rotas e permissões por perfil de usuario.
3. Consolidar comandos de teste frontend/E2E em documentacao versionada dentro de `docs/`.

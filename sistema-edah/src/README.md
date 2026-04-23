# Sistema EDAH — Backend Django

Sistema de gestão de igrejas com API REST para o app mobile Flutter.

## Tecnologias

- Python 3.12 + Django 5
- Django REST Framework + SimpleJWT (JWT)
- SQLite (desenvolvimento) / PostgreSQL (produção)
- pytest + pytest-cov (cobertura mínima: 80%)

## Estrutura

```
django-sis-igreja/
├── church/
│   ├── models/            # Modelos de dados
│   ├── views_app/         # Views da API mobile e web
│   ├── api_urls.py        # Rotas da API /api/v1/
│   ├── api_serializers.py # Serializers DRF
│   └── permissions.py     # IsMembroAtivo, IsAdminIgreja, etc.
├── config/
│   ├── settings.py        # Configurações (single/multi-tenant)
│   └── urls.py
└── tests/                 # Suite de testes
```

## Rodando localmente

```bash
# 1. Ativar ambiente virtual
source .venv/bin/activate

# 2. Aplicar migrations
DATABASE_URL= python manage.py migrate

# 3. Criar superusuário para o painel admin
DATABASE_URL= python manage.py createsuperuser

# 4. Iniciar servidor
DATABASE_URL= python manage.py runserver
```

> O prefixo `DATABASE_URL=` força o modo single-tenant (SQLite),
> ignorando o PostgreSQL configurado no `.env`.

## Acessos

| URL | Descrição |
|-----|-----------|
| `http://localhost:8000/admin/` | Painel administrativo Django |
| `http://localhost:8000/` | Webapp web |
| `http://localhost:8000/api/v1/` | API REST para o app mobile |

## Autenticação do App Mobile

O app Flutter usa **código de acesso pessoal** — sem email ou senha.

### Como funciona

1. Admin cadastra o membro em `/admin/ → Membros → Adicionar`
2. O sistema gera automaticamente um código de **6 caracteres alfanuméricos** (ex: `4A7K92`)
3. Admin visualiza o código em **Membros → [membro] → Código de acesso** e o entrega ao membro (papel, WhatsApp, etc.)
4. Membro digita o código no app → recebe token JWT → acesso liberado

### Endpoint de autenticação por código

```
POST /api/v1/auth/codigo/
Content-Type: application/json

{ "codigo": "4A7K92" }
```

**Resposta de sucesso (200):**
```json
{
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>",
  "usuario": {
    "id": 1,
    "nome": "João Silva",
    "email": "joao@email.com",
    "nivel_acesso": "usuario"
  }
}
```

**Respostas de erro:**
- `401` — Código inválido ou membro inativo
- `429` — Rate limit atingido (5 tentativas por minuto por IP)

### Regenerar código de um membro

Se um membro perder o código, o admin pode regenerar via shell:

```bash
DATABASE_URL= python manage.py shell -c "
from church.models import Membro
m = Membro.objects.get(pessoa__nome='Nome do Membro')
m.codigo_acesso = ''
m.save()
print('Novo código:', m.codigo_acesso)
"
```

## Testes

```bash
DATABASE_URL= python -m pytest tests/ -q
# Cobertura mínima exigida: 80%
```

## Variáveis de ambiente (`.env`)

| Variável | Descrição |
|----------|-----------|
| `DATABASE_URL` | URL PostgreSQL (se vazio → SQLite) |
| `DEBUG` | `True` para desenvolvimento |
| `DJANGO_SECRET_KEY` | Chave secreta Django (obrigatória em produção) |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Origens CORS (app Flutter) |
| `FIREBASE_CREDENTIALS_JSON` | Caminho para credenciais FCM (push notifications) |

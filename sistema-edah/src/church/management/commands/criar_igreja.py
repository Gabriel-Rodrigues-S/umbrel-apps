"""
Management command para provisionar uma nova igreja no sistema SaaS.

Uso:
    python manage.py criar_igreja \\
        --nome "Igreja Batista de Manaus" \\
        --schema "batista_manaus" \\
        --dominio "batista-manaus.seuapp.com.br" \\
        --email "secretaria@batista-manaus.com.br" \\
        --responsavel "Pastor João Silva" \\
        --codigo "IBMANAUS"

Requer PostgreSQL + django-tenants configurados.
"""

import secrets

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Provisiona uma nova igreja no sistema SaaS multi-tenant"

    def add_arguments(self, parser):
        parser.add_argument("--nome",        required=True,  help="Nome completo da igreja")
        parser.add_argument("--schema",      required=True,  help="Schema PostgreSQL (ex: batista_manaus)")
        parser.add_argument("--dominio",     required=True,  help="Domínio primário (ex: batista-manaus.seuapp.com.br)")
        parser.add_argument("--email",       required=True,  help="E-mail do admin/responsável da igreja")
        parser.add_argument("--responsavel", required=True,  help="Nome do pastor/responsável")
        parser.add_argument("--codigo",      required=True,  help="Código de acesso curto (ex: IBMANAUS)")

    def handle(self, *args, **options):
        try:
            from django_tenants.utils import schema_context
        except ImportError:
            raise CommandError(
                "django-tenants não está instalado. "
                "Execute: pip install django-tenants e configure DATABASE_URL com PostgreSQL."
            )

        from church.tenants.models import Domain, Igreja

        schema_name = options["schema"]
        codigo      = options["codigo"].upper()

        # Validações preventivas
        if Igreja.objects.filter(schema_name=schema_name).exists():
            raise CommandError(f"Schema '{schema_name}' já existe.")

        if Igreja.objects.filter(codigo_acesso=codigo).exists():
            raise CommandError(f"Código de acesso '{codigo}' já está em uso.")

        if Domain.objects.filter(domain=options["dominio"]).exists():
            raise CommandError(f"Domínio '{options['dominio']}' já está em uso.")

        # 1. Criar o tenant (cria o schema PostgreSQL automaticamente)
        self.stdout.write(f"→ Criando schema '{schema_name}'...")
        igreja = Igreja.objects.create(
            schema_name=schema_name,
            nome=options["nome"],
            email_contato=options["email"],
            responsavel=options["responsavel"],
            codigo_acesso=codigo,
        )

        # 2. Criar o domínio principal
        Domain.objects.create(
            domain=options["dominio"],
            tenant=igreja,
            is_primary=True,
        )
        self.stdout.write(f"→ Domínio '{options['dominio']}' configurado.")

        # 3. Dentro do schema da nova igreja, criar o usuário admin inicial
        senha_inicial = secrets.token_urlsafe(16)
        with schema_context(schema_name):
            from church.models import User
            User.objects.create_superuser(
                email=options["email"],
                nome=options["responsavel"],
                password=senha_inicial,
                nivel_acesso="admin",
            )
        self.stdout.write("→ Usuário admin criado.")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nIgreja '{options['nome']}' provisionada com sucesso!\n"
                f"  Schema  : {schema_name}\n"
                f"  URL     : https://{options['dominio']}\n"
                f"  Código  : {codigo}\n"
                f"  Admin   : {options['email']}\n"
                f"  Senha   : {senha_inicial}\n"
                f"\n  ⚠  Anote a senha acima — ela não será exibida novamente."
                f"\n  ⚠  Oriente o responsável a trocar a senha no primeiro acesso."
            )
        )

"""
Management command para criar o tenant público (schema 'public') do SaaS.
Deve ser executado uma única vez na configuração inicial do servidor.

Uso:
    python manage.py criar_tenant_publico --dominio admin.seuapp.com.br
"""

import secrets
import string

from django.core.management.base import BaseCommand, CommandError


def _gerar_codigo():
    alfabeto = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(10))


class Command(BaseCommand):
    help = "Cria o tenant público (schema 'public') para o painel super-admin do SaaS"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dominio",
            required=True,
            help="Domínio do painel admin (ex: admin.seuapp.com.br)",
        )
        parser.add_argument(
            "--email",
            default="admin@seuapp.com.br",
            help="E-mail do super-admin (padrão: admin@seuapp.com.br)",
        )

    def handle(self, *args, **options):
        from church.tenants.models import Domain, Igreja

        if Igreja.objects.filter(schema_name="public").exists():
            raise CommandError(
                "Tenant público já existe. Execute este comando apenas uma vez."
            )

        if Domain.objects.filter(domain=options["dominio"]).exists():
            raise CommandError(f"Domínio '{options['dominio']}' já está em uso.")

        codigo = _gerar_codigo()

        self.stdout.write("→ Criando tenant público...")
        public = Igreja.objects.create(
            schema_name="public",
            nome="SaaS Admin",
            email_contato=options["email"],
            responsavel="Super Admin",
            codigo_acesso=codigo,
        )
        Domain.objects.create(
            domain=options["dominio"],
            tenant=public,
            is_primary=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTenant público criado com sucesso!\n"
                f"  Domínio : {options['dominio']}\n"
                f"  Código  : {codigo}\n"
                f"\n  Acesse o painel em: https://{options['dominio']}/admin/"
            )
        )

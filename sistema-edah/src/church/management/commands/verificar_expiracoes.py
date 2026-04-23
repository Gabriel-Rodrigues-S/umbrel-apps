"""
Management command para desativar igrejas com contrato expirado.

Agendar via cron no servidor:
    0 8 * * * /caminho/venv/bin/python /caminho/manage.py verificar_expiracoes

Requer PostgreSQL + django-tenants configurados.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Desativa automaticamente igrejas com contrato expirado"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas lista as igrejas que seriam desativadas, sem alterar nada.",
        )

    def handle(self, *args, **options):
        try:
            from church.tenants.models import Igreja
        except ImportError:
            raise CommandError(
                "django-tenants não está instalado ou DATABASE_URL não configurada."
            )

        from django.utils import timezone
        hoje = timezone.now().date()

        expiradas = Igreja.objects.filter(
            data_expiracao__lt=hoje,
            ativo=True,
        )

        if not expiradas.exists():
            self.stdout.write(self.style.SUCCESS("Nenhuma igreja com contrato expirado."))
            return

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"[DRY RUN] {expiradas.count()} igreja(s) seriam desativadas:"))
            for ig in expiradas:
                self.stdout.write(f"  - {ig.nome} (expiração: {ig.data_expiracao})")
            return

        nomes = list(expiradas.values_list("nome", flat=True))
        count = expiradas.update(ativo=False)

        self.stdout.write(
            self.style.SUCCESS(f"{count} igreja(s) desativada(s):")
        )
        for nome in nomes:
            self.stdout.write(f"  - {nome}")

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from church.models import CategoriaFinanceira, Igreja, TipoCategoria, User


class Command(BaseCommand):
    help = "Cria usuário admin padrão, igreja e categorias financeiras (idempotente)."

    def handle(self, *args, **options):
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@igreja.com").strip()
        if not User.objects.filter(email=email).exists():
            password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
            if not password:
                if settings.DEBUG:
                    password = "admin123"
                    self.stdout.write(
                        self.style.WARNING(
                            "BOOTSTRAP_ADMIN_PASSWORD nao definida. Usando senha padrao local 'admin123' (DEBUG=True)."
                        )
                    )
                else:
                    raise CommandError(
                        "Defina BOOTSTRAP_ADMIN_PASSWORD para criar o superusuario inicial de forma segura."
                    )
            User.objects.create_superuser(
                email=email,
                password=password,
                nome="Administrador",
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Superusuario criado: {email}. Altere a senha apos o primeiro acesso."
                )
            )
        else:
            self.stdout.write("Superusuario ja existe - ignorando.")

        if not Igreja.objects.exists():
            Igreja.objects.create(
                nome="Igreja EDAH",
                cnpj="00.000.000/0001-00",
                endereco="Rua Exemplo, 123",
                bairro="Centro",
                cidade="Sua Cidade",
                estado="SP",
                cep="00000-000",
                telefone="(00) 0000-0000",
                email="contato@igreja.com",
            )
            self.stdout.write(self.style.SUCCESS("Registro de igreja inicial criado."))

        defaults = [
            ("Dízimos", TipoCategoria.ENTRADA, "Dízimos dos membros"),
            ("Ofertas", TipoCategoria.ENTRADA, "Ofertas diversas"),
            ("Doações", TipoCategoria.ENTRADA, "Doações específicas"),
            ("Água e Luz", TipoCategoria.SAIDA, "Despesas com água e energia elétrica"),
            ("Aluguel", TipoCategoria.SAIDA, "Pagamento de aluguel"),
            ("Salários", TipoCategoria.SAIDA, "Pagamento de funcionários"),
            ("Manutenção", TipoCategoria.SAIDA, "Manutenção predial e equipamentos"),
            ("Materiais", TipoCategoria.SAIDA, "Compra de materiais diversos"),
        ]
        for nome, tipo, desc in defaults:
            CategoriaFinanceira.objects.get_or_create(
                nome=nome,
                defaults={"tipo": tipo, "descricao": desc},
            )
        self.stdout.write(self.style.SUCCESS("Categorias financeiras verificadas."))

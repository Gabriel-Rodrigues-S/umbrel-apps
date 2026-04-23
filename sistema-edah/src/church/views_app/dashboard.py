import json
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, Count, IntegerField, Q, Sum, Value, When
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.views.generic import TemplateView

from church.models import Evento, LancamentoFinanceiro, Membro, PequenoGrupo, StatusAtivo, StatusEvento, StatusMembro, TipoLancamento, Visitante


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "app/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        mes, ano = now.month, now.year

        ctx["total_membros"] = Membro.objects.filter(status=StatusMembro.ATIVO).count()
        ctx["visitantes_mes"] = Visitante.objects.filter(
            data_ultima_visita__month=mes,
            data_ultima_visita__year=ano,
        ).count()
        ctx["pequenos_grupos"] = PequenoGrupo.objects.filter(status=StatusAtivo.ATIVO).count()
        receita = (
            LancamentoFinanceiro.objects.filter(
                tipo__in=[
                    TipoLancamento.DIZIMO,
                    TipoLancamento.OFERTA,
                    TipoLancamento.DOACAO,
                ],
                data_lancamento__month=mes,
                data_lancamento__year=ano,
            ).aggregate(t=Sum("valor"))["t"]
        )
        ctx["receita_mes"] = receita or 0

        ctx["proximos_eventos"] = (
            Evento.objects.filter(
                data_inicio__gte=now,
                status__in=[StatusEvento.PLANEJAMENTO, StatusEvento.ABERTO],
            )
            .order_by("data_inicio")[:5]
        )

        year_ago = now - timedelta(days=365)
        chart = (
            Membro.objects.filter(pessoa__data_cadastro__gte=year_ago)
            .annotate(m=TruncMonth("pessoa__data_cadastro"))
            .values("m")
            .annotate(c=Count("id"))
            .order_by("m")
        )
        labels = []
        data = []
        for row in chart:
            if row["m"]:
                labels.append(row["m"].strftime("%b"))
                data.append(row["c"])
        if not labels:
            labels = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
            data = [0] * 12
        ctx["membros_chart_labels"] = json.dumps(labels)
        ctx["membros_chart_data"] = json.dumps(data)

        today = timezone.now().date()
        faixa_qs = (
            Membro.objects.filter(status=StatusMembro.ATIVO)
            .annotate(
                faixa=Case(
                    When(Q(pessoa__data_nascimento__isnull=False) & Q(pessoa__data_nascimento__gt=today.replace(year=today.year - 13)), then=Value(0)),
                    When(Q(pessoa__data_nascimento__isnull=False) & Q(pessoa__data_nascimento__gt=today.replace(year=today.year - 18)), then=Value(1)),
                    When(Q(pessoa__data_nascimento__isnull=False) & Q(pessoa__data_nascimento__gt=today.replace(year=today.year - 36)), then=Value(2)),
                    When(Q(pessoa__data_nascimento__isnull=False) & Q(pessoa__data_nascimento__gt=today.replace(year=today.year - 61)), then=Value(3)),
                    When(Q(pessoa__data_nascimento__isnull=False), then=Value(4)),
                    default=Value(-1),
                    output_field=IntegerField(),
                )
            )
            .values("faixa")
            .annotate(c=Count("id"))
        )
        faixa = [0, 0, 0, 0, 0]
        for row in faixa_qs:
            if row["faixa"] >= 0:
                faixa[row["faixa"]] += row["c"]
        faixa_labels = [
            "0-12 anos",
            "13-17 anos",
            "18-35 anos",
            "36-60 anos",
            "60+ anos",
        ]
        ctx["faixa_labels_json"] = json.dumps(faixa_labels)
        ctx["faixa_data_json"] = json.dumps(faixa)

        return ctx

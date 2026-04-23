from django.conf import settings
from django.db import models

from .cadastros import Pessoa


class TipoCategoria(models.TextChoices):
    ENTRADA = "entrada", "Entrada"
    SAIDA = "saida", "Saída"


class StatusCategoria(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    INATIVO = "inativo", "Inativo"


class CategoriaFinanceira(models.Model):
    nome = models.CharField(max_length=150)
    tipo = models.CharField(max_length=10, choices=TipoCategoria.choices)
    descricao = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=StatusCategoria.choices,
        default=StatusCategoria.ATIVO,
    )

    class Meta:
        db_table = "categorias_financeiras"
        verbose_name_plural = "categorias financeiras"

    def __str__(self):
        return self.nome


class TipoLancamento(models.TextChoices):
    DIZIMO = "dizimo", "Dízimo"
    OFERTA = "oferta", "Oferta"
    DOACAO = "doacao", "Doação"
    SAIDA = "saida", "Saída"
    OUTRO = "outro", "Outro"


class MetodoPagamento(models.TextChoices):
    DINHEIRO = "dinheiro", "Dinheiro"
    CARTAO_CREDITO = "cartao_credito", "Cartão de crédito"
    CARTAO_DEBITO = "cartao_debito", "Cartão de débito"
    PIX = "pix", "PIX"
    TRANSFERENCIA = "transferencia", "Transferência"
    CHEQUE = "cheque", "Cheque"


class LancamentoFinanceiro(models.Model):
    tipo = models.CharField(max_length=20, choices=TipoLancamento.choices)
    categoria = models.ForeignKey(
        CategoriaFinanceira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos",
        db_column="categoria_id",
    )
    pessoa = models.ForeignKey(
        Pessoa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos_financeiros",
        db_column="pessoa_id",
    )
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data_lancamento = models.DateField()
    descricao = models.TextField(blank=True, null=True)
    metodo_pagamento = models.CharField(
        max_length=30,
        choices=MetodoPagamento.choices,
        blank=True,
        null=True,
    )
    comprovante = models.CharField(max_length=255, blank=True, null=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lancamentos_registrados",
        db_column="usuario_id",
    )
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lancamentos_financeiros"
        indexes = [
            models.Index(fields=["data_lancamento"]),
            models.Index(fields=["tipo"]),
        ]

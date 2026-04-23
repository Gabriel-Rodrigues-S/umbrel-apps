"""
Remove o campo 'plano' do modelo Igreja.
O sistema passa a usar apenas os campos 'ativo' e 'data_expiracao'
para controlar o acesso da igreja (assinatura ativa/inativa).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="igreja",
            name="plano",
        ),
    ]

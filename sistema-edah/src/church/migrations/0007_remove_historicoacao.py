"""
Remove o modelo HistoricoAcao — modelo definido mas nunca utilizado na aplicação.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("church", "0006_indexes_performance"),
    ]

    operations = [
        migrations.DeleteModel(
            name="HistoricoAcao",
        ),
    ]

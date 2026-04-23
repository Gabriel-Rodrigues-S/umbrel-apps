"""
Adiciona índices de performance:
- Pessoa.email (db_index): consultado em toda autenticação via código de acesso
- Mensagem(destinatario, lida): consultado no chat_ping e chat_contatos
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("church", "0005_add_codigo_acesso_membro"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pessoa",
            name="email",
            field=models.EmailField(blank=True, db_index=True, max_length=150, null=True),
        ),
        migrations.AddIndex(
            model_name="mensagem",
            index=models.Index(fields=["destinatario", "lida"], name="msg_dest_lida_idx"),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clientes', '0017_notificacion_actor_pedido_detalle'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='estimado_kg',
            field=models.IntegerField(default=0),
        ),
    ]


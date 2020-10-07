# Generated by Django 2.2.4 on 2020-10-05 15:59

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('merlinservices', '0003_balanceverification_equipment_equipmenttype'),
    ]

    operations = [
        migrations.AlterField(
            model_name='balanceverification',
            name='analyst',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='balance_verifications', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='balanceverification',
            name='balance',
            field=models.ForeignKey(limit_choices_to={'type': 1}, on_delete=django.db.models.deletion.CASCADE, related_name='balance_verifications', to='merlinservices.Equipment'),
        ),
    ]
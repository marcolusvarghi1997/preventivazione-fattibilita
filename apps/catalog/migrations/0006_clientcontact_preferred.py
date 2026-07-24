from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0005_landeviceaccess_mac_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientcontact",
            name="preferred",
            field=models.BooleanField(default=False, verbose_name="Preferito"),
        ),
        migrations.AddConstraint(
            model_name="clientcontact",
            constraint=models.UniqueConstraint(
                condition=models.Q(preferred=True),
                fields=("client",),
                name="unique_preferred_contact_per_client",
            ),
        ),
    ]

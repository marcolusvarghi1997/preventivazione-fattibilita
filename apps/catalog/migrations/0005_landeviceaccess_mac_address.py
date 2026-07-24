from django.db import migrations, models


def reset_ip_only_permissions(apps, schema_editor):
    LanDeviceAccess = apps.get_model("catalog", "LanDeviceAccess")
    LanDeviceAccess.objects.filter(status="allowed").update(
        status="pending",
        decided_at=None,
        decided_by=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_clientcontact_unique_contact_name_per_client_ci_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="landeviceaccess",
            name="mac_address",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Rilevato dal server tramite la tabella di rete locale.",
                max_length=17,
                verbose_name="Indirizzo MAC",
            ),
        ),
        migrations.RunPython(reset_ip_only_permissions, migrations.RunPython.noop),
    ]

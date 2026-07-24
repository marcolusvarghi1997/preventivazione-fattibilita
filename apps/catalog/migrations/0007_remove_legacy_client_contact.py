from django.db import migrations


def migrate_legacy_preferred_contacts(apps, schema_editor):
    Client = apps.get_model("catalog", "Client")
    ClientContact = apps.get_model("catalog", "ClientContact")
    for client in Client.objects.exclude(contact_name="").iterator():
        if not ClientContact.objects.filter(client=client, preferred=True).exists():
            ClientContact.objects.filter(
                client=client,
                name__iexact=client.contact_name,
            ).update(preferred=True)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_clientcontact_preferred"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_preferred_contacts, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="client",
            name="contact_name",
        ),
    ]

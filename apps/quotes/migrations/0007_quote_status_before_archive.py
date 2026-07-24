from django.db import migrations, models


def initialize_archived_status(apps, schema_editor):
    Quote = apps.get_model("quotes", "Quote")
    Quote.objects.filter(status="archived").update(status_before_archive="draft")


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0006_quoteitem_preserve_after_quote_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="status_before_archive",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                max_length=20,
                verbose_name="Stato precedente all’archiviazione",
            ),
        ),
        migrations.RunPython(initialize_archived_status, migrations.RunPython.noop),
    ]

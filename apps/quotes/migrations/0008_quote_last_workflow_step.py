from django.db import migrations, models


def initialize_workflow_step(apps, schema_editor):
    Quote = apps.get_model("quotes", "Quote")
    Quote.objects.filter(items__isnull=False).distinct().update(last_workflow_step=4)


class Migration(migrations.Migration):
    dependencies = [
        ("quotes", "0007_quote_status_before_archive"),
    ]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="last_workflow_step",
            field=models.PositiveSmallIntegerField(default=2, editable=False, verbose_name="Ultimo passaggio visitato"),
        ),
        migrations.RunPython(initialize_workflow_step, migrations.RunPython.noop),
    ]

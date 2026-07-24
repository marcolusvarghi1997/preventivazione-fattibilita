from django.db import migrations, models


def populate_missing_revisions(apps, schema_editor):
    QuoteItem = apps.get_model("quotes", "QuoteItem")
    QuoteItem.objects.filter(revision="").update(revision="00")


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0003_quoteitem_versioning"),
    ]

    operations = [
        migrations.RunPython(populate_missing_revisions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="quoteitem",
            name="revision",
            field=models.CharField(max_length=50, verbose_name="Revisione"),
        ),
        migrations.AlterModelOptions(
            name="quoteitem",
            options={
                "ordering": ["display_order", "id"],
                "verbose_name": "articolo",
                "verbose_name_plural": "storico articoli",
            },
        ),
        migrations.AddIndex(
            model_name="quoteitem",
            index=models.Index(
                fields=["code", "revision", "-created_at"],
                name="quoteitem_key_created_idx",
            ),
        ),
    ]

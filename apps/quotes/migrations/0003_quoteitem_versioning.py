from django.db import migrations, models
import django.db.models.deletion


def populate_historical_version_timestamps(apps, schema_editor):
    QuoteItem = apps.get_model("quotes", "QuoteItem")
    items = list(QuoteItem.objects.select_related("quote").all())
    for item in items:
        item.created_at = item.quote.created_at
    if items:
        QuoteItem.objects.bulk_update(items, ["created_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0002_quote_client_email_quote_customer_decision_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="quoteitem",
            name="created_at",
            field=models.DateTimeField(editable=False, null=True, verbose_name="Creata il"),
        ),
        migrations.AddField(
            model_name="quoteitem",
            name="creation_token",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="quoteitem",
            name="source_version",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="derived_versions",
                to="quotes.quoteitem",
                verbose_name="Versione sorgente",
            ),
        ),
        migrations.RunPython(
            populate_historical_version_timestamps,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="quoteitem",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, editable=False, verbose_name="Creata il"),
        ),
        migrations.AddIndex(
            model_name="quoteitem",
            index=models.Index(
                fields=["code", "-created_at"],
                name="quoteitem_code_created_idx",
            ),
        ),
    ]

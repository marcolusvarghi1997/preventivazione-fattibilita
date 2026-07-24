from django.db import migrations, models
from django.utils import timezone


def populate_article_dates(apps, schema_editor):
    QuoteItem = apps.get_model("quotes", "QuoteItem")
    items = list(QuoteItem.objects.all())
    for item in items:
        item.article_date = timezone.localtime(item.created_at).date()
    if items:
        QuoteItem.objects.bulk_update(items, ["article_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0004_quoteitem_combined_key_search"),
    ]

    operations = [
        migrations.AddField(
            model_name="quoteitem",
            name="article_date",
            field=models.DateField(db_index=True, editable=False, null=True, verbose_name="Data articolo"),
        ),
        migrations.RunPython(populate_article_dates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="quoteitem",
            name="article_date",
            field=models.DateField(
                db_index=True,
                default=timezone.localdate,
                editable=False,
                verbose_name="Data articolo",
            ),
        ),
        migrations.RemoveIndex(
            model_name="quoteitem",
            name="quoteitem_code_created_idx",
        ),
        migrations.RemoveIndex(
            model_name="quoteitem",
            name="quoteitem_key_created_idx",
        ),
        migrations.RemoveField(
            model_name="quoteitem",
            name="created_at",
        ),
        migrations.AddIndex(
            model_name="quoteitem",
            index=models.Index(
                fields=["code", "-article_date"],
                name="quoteitem_code_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="quoteitem",
            index=models.Index(
                fields=["code", "revision", "-article_date"],
                name="quoteitem_key_date_idx",
            ),
        ),
    ]

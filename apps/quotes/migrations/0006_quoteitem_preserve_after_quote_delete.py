from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("quotes", "0005_quoteitem_article_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quoteitem",
            name="quote",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="items",
                to="quotes.quote",
                verbose_name="Preventivo",
            ),
        ),
    ]

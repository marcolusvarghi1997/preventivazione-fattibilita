from decimal import Decimal, InvalidOperation
import re

import django.core.validators
from django.db import migrations, models


def migrate_dimensions(apps, schema_editor):
    QuoteItem = apps.get_model("quotes", "QuoteItem")
    for item in QuoteItem.objects.exclude(legacy_dimensions="").iterator():
        values = re.findall(r"\d+(?:[.,]\d+)?", item.legacy_dimensions)
        parsed = []
        for value in values[:3]:
            try:
                parsed.append(Decimal(value.replace(",", ".")))
            except InvalidOperation:
                break
        if parsed and all(value > 0 for value in parsed):
            fields = ("length_mm", "height_mm", "depth_mm")
            for field, value in zip(fields, parsed):
                setattr(item, field, value)
            item.save(update_fields=list(fields[:len(parsed)]))


class Migration(migrations.Migration):
    dependencies = [
        ("quotes", "0008_quote_last_workflow_step"),
    ]

    operations = [
        migrations.RenameField(
            model_name="quoteitem",
            old_name="dimensions",
            new_name="legacy_dimensions",
        ),
        migrations.AlterField(
            model_name="quote",
            name="feasibility",
            field=models.CharField(
                choices=[
                    ("internal", "Fattibile internamente"),
                    ("to_check", "Da verificare"),
                    ("not_feasible", "Non fattibile"),
                ],
                db_index=True,
                default="to_check",
                max_length=20,
                verbose_name="Fattibilita",
            ),
        ),
        migrations.AlterField(
            model_name="quoteitem",
            name="feasibility",
            field=models.CharField(
                choices=[
                    ("internal", "Fattibile internamente"),
                    ("to_check", "Da verificare"),
                    ("not_feasible", "Non fattibile"),
                ],
                default="to_check",
                max_length=20,
                verbose_name="Fattibilita articolo",
            ),
        ),
        migrations.AddField(
            model_name="quoteitem",
            name="length_mm",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                verbose_name="Lunghezza",
            ),
        ),
        migrations.AddField(
            model_name="quoteitem",
            name="height_mm",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                verbose_name="Altezza",
            ),
        ),
        migrations.AddField(
            model_name="quoteitem",
            name="depth_mm",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                verbose_name="Profondità",
            ),
        ),
        migrations.RunPython(migrate_dimensions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="quoteitem",
            constraint=models.CheckConstraint(
                condition=models.Q(length_mm__isnull=True) | models.Q(length_mm__gt=0),
                name="item_length_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="quoteitem",
            constraint=models.CheckConstraint(
                condition=models.Q(height_mm__isnull=True) | models.Q(height_mm__gt=0),
                name="item_height_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="quoteitem",
            constraint=models.CheckConstraint(
                condition=models.Q(depth_mm__isnull=True) | models.Q(depth_mm__gt=0),
                name="item_depth_positive",
            ),
        ),
    ]

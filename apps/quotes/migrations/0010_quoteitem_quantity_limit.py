import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("quotes", "0009_quoteitem_dimensions_and_feasibility_order"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="quoteitem",
            name="item_quantity_positive",
        ),
        migrations.AlterField(
            model_name="quoteitem",
            name="quantity",
            field=models.PositiveIntegerField(
                default=1,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(99999),
                ],
                verbose_name="Quantita",
            ),
        ),
        migrations.AddConstraint(
            model_name="quoteitem",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gte=1, quantity__lte=99999),
                name="item_quantity_positive",
            ),
        ),
    ]

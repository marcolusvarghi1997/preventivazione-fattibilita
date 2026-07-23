from django.db import models

from .forms import ItalianDecimalField, ItalianDecimalInput


class ItalianDecimalAdminMixin:
    """Uniforma l'inserimento Decimal nell'admin senza cambiare i modelli."""

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, models.DecimalField):
            places = 3 if "weight" in db_field.name else 2
            kwargs["form_class"] = ItalianDecimalField
            kwargs["widget"] = ItalianDecimalInput(places=places)
            kwargs["display_places"] = places
        return super().formfield_for_dbfield(db_field, request, **kwargs)

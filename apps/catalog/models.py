from decimal import Decimal
from django.db import models


class Client(models.Model):
    name = models.CharField("Ragione sociale", max_length=200, db_index=True)
    contact_name = models.CharField("Referente predefinito", max_length=150, blank=True)
    email = models.EmailField("Email", blank=True)
    phone = models.CharField("Telefono", max_length=50, blank=True)
    address = models.TextField("Indirizzo", blank=True)
    active = models.BooleanField("Attivo", default=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clienti"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Material(models.Model):
    name = models.CharField("Nome", max_length=150, unique=True)
    description = models.TextField("Descrizione", blank=True)
    current_cost_per_kg = models.DecimalField("Costo corrente al kg", max_digits=12, decimal_places=4, null=True, blank=True)
    active = models.BooleanField("Attivo", default=True)

    class Meta:
        verbose_name = "materiale"
        verbose_name_plural = "materiali"
        ordering = ["name"]
        constraints = [models.CheckConstraint(condition=models.Q(current_cost_per_kg__gte=0), name="material_cost_non_negative")]

    def __str__(self) -> str:
        return self.name


class PhaseDefinition(models.Model):
    code = models.SlugField("Codice", max_length=50, unique=True)
    name = models.CharField("Nome", max_length=120)
    display_order = models.PositiveSmallIntegerField("Ordine", unique=True)
    active = models.BooleanField("Attiva", default=True)

    class Meta:
        verbose_name = "fase"
        verbose_name_plural = "fasi"
        ordering = ["display_order"]

    def __str__(self) -> str:
        return self.name


class ProductionResource(models.Model):
    class ResourceType(models.TextChoices):
        MACHINE = "machine", "Macchina"
        MANUAL = "manual", "Attivita manuale"
        FIXED = "fixed", "Lavorazione fissa"

    name = models.CharField("Nome", max_length=150)
    internal_code = models.CharField("Codice interno", max_length=50, blank=True)
    phase = models.ForeignKey(PhaseDefinition, on_delete=models.PROTECT, related_name="resources", verbose_name="Fase")
    hourly_cost_per_person = models.DecimalField("Costo orario per persona", max_digits=12, decimal_places=4, default=Decimal("0"))
    default_operators = models.PositiveSmallIntegerField("Operatori predefiniti", default=1)
    resource_type = models.CharField("Tipo risorsa", max_length=20, choices=ResourceType.choices)
    user_selectable = models.BooleanField("Selezionabile dall'utente", default=True)
    active = models.BooleanField("Attiva", default=True)
    notes = models.TextField("Note", blank=True)

    class Meta:
        verbose_name = "risorsa produttiva"
        verbose_name_plural = "risorse produttive"
        ordering = ["phase__display_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["phase", "name"], name="unique_resource_per_phase"),
            models.CheckConstraint(condition=models.Q(hourly_cost_per_person__gte=0), name="resource_cost_non_negative"),
            models.CheckConstraint(condition=models.Q(default_operators__gte=1), name="resource_operators_positive"),
        ]

    @property
    def cost_configured(self) -> bool:
        return self.hourly_cost_per_person > 0

    def __str__(self) -> str:
        return self.name

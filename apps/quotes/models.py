from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, OperationalError, models, transaction
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import Client, Material, PhaseDefinition, ProductionResource

ZERO = Decimal("0")


class Feasibility(models.TextChoices):
    INTERNAL = "internal", "Fattibile internamente"
    TO_CHECK = "to_check", "Da verificare"
    NOT_FEASIBLE = "not_feasible", "Non fattibile"


class QuoteSequence(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)


def next_quote_number() -> str:
    year = timezone.localdate().year
    for _ in range(5):
        try:
            with transaction.atomic():
                sequence, _ = QuoteSequence.objects.get_or_create(year=year)
                QuoteSequence.objects.filter(pk=sequence.pk).update(last_number=F("last_number") + 1)
                sequence.refresh_from_db(fields=["last_number"])
                return f"PR-{year}-{sequence.last_number:05d}"
        except (IntegrityError, OperationalError):
            continue
    raise RuntimeError("Impossibile generare il numero preventivo. Riprovare.")


class Quote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Bozza"
        IN_PROGRESS = "in_progress", "In lavorazione"
        COMPLETED = "completed", "Completato"
        REJECTED = "rejected", "Rifiutato"
        SENT = "sent", "Inviato"
        ARCHIVED = "archived", "Archiviato"

    class CustomerDecision(models.TextChoices):
        PENDING = "pending", "Da definire"
        ACCEPTED = "accepted", "Accettato"
        REJECTED = "rejected", "Rifiutato"

    number = models.CharField("Numero", max_length=30, unique=True, blank=True, db_index=True)
    date = models.DateField("Data", default=timezone.localdate, db_index=True)
    status = models.CharField("Stato", max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    status_before_archive = models.CharField(
        "Stato precedente all’archiviazione",
        max_length=20,
        blank=True,
        default="",
        editable=False,
    )
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="quotes", verbose_name="Cliente")
    client_contact = models.CharField("Referente cliente", max_length=150, blank=True)
    client_email = models.EmailField("Email referente", blank=True)
    internal_notes = models.TextField("Note interne", blank=True)
    customer_notes = models.TextField("Note visibili al cliente", blank=True)
    feasibility = models.CharField("Fattibilita", max_length=20, choices=Feasibility.choices, default=Feasibility.TO_CHECK, db_index=True)
    offered_price = models.DecimalField("Prezzo commerciale offerto", max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    customer_decision = models.CharField(
        "Esito cliente",
        max_length=20,
        choices=CustomerDecision.choices,
        default=CustomerDecision.PENDING,
        db_index=True,
    )
    last_workflow_step = models.PositiveSmallIntegerField(
        "Ultimo passaggio visitato",
        default=2,
        editable=False,
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="quotes", verbose_name="Autore")
    created_at = models.DateTimeField("Creato il", auto_now_add=True)
    updated_at = models.DateTimeField("Modificato il", auto_now=True)

    class Meta:
        verbose_name = "preventivo"
        verbose_name_plural = "preventivi"
        ordering = ["-date", "-id"]
        permissions = [
            ("duplicate_quote", "Puo duplicare preventivi"),
            ("archive_quote", "Puo archiviare preventivi"),
            ("generate_quote_pdf", "Puo generare PDF preventivi"),
        ]

    def save(self, *args, **kwargs) -> None:
        if not self.number:
            self.number = next_quote_number()
        super().save(*args, **kwargs)

    @property
    def industrial_cost(self) -> Decimal:
        return sum((item.total_cost for item in self.items.all()), ZERO)

    @property
    def difference(self) -> Decimal | None:
        return None if self.offered_price is None else self.offered_price - self.industrial_cost

    @property
    def margin_percent(self) -> Decimal | None:
        if not self.offered_price or self.offered_price <= 0:
            return None
        return (self.offered_price - self.industrial_cost) / self.offered_price * Decimal("100")

    @property
    def profit_percent(self) -> Decimal | None:
        """Guadagno percentuale calcolato sul costo industriale (markup)."""
        if self.offered_price is None or self.industrial_cost <= 0:
            return None
        return (self.offered_price - self.industrial_cost) / self.industrial_cost * Decimal("100")

    @property
    def display_status(self) -> str:
        if self.status == self.Status.ARCHIVED:
            return "Archiviato"
        if self.status == self.Status.REJECTED or self.customer_decision == self.CustomerDecision.REJECTED:
            return "Rifiutato"
        if self.status == self.Status.COMPLETED or self.customer_decision == self.CustomerDecision.ACCEPTED:
            return "Completato"
        return self.get_status_display()

    @property
    def status_css_class(self) -> str:
        return {
            "Archiviato": "archived",
            "Rifiutato": "rejected",
            "Completato": "completed",
            "In lavorazione": "in-progress",
            "Inviato": "sent",
        }.get(self.display_status, "draft")

    @property
    def feasibility_css_class(self) -> str:
        return {
            Feasibility.INTERNAL: "internal",
            Feasibility.TO_CHECK: "to-check",
            Feasibility.NOT_FEASIBLE: "not-feasible",
        }[self.feasibility]

    def __str__(self) -> str:
        return self.number


class QuoteItem(models.Model):
    quote = models.ForeignKey(
        Quote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
        verbose_name="Preventivo",
    )
    source_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_versions",
        editable=False,
        verbose_name="Versione sorgente",
    )
    code = models.CharField("Codice", max_length=100, db_index=True)
    article_date = models.DateField("Data articolo", default=timezone.localdate, db_index=True, editable=False)
    quantity = models.PositiveIntegerField(
        "Quantita", default=1, validators=[MinValueValidator(1), MaxValueValidator(99999)]
    )
    description = models.CharField("Descrizione", max_length=250, blank=True, db_index=True)
    revision = models.CharField("Revisione", max_length=50)
    legacy_dimensions = models.CharField("Dimensioni", max_length=150, blank=True)
    length_mm = models.DecimalField(
        "Lunghezza", max_digits=12, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    height_mm = models.DecimalField(
        "Altezza", max_digits=12, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    depth_mm = models.DecimalField(
        "Profondità", max_digits=12, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    technical_notes = models.TextField("Note tecniche", blank=True)
    feasibility = models.CharField("Fattibilita articolo", max_length=20, choices=Feasibility.choices, default=Feasibility.TO_CHECK)
    external_purchases = models.BooleanField("Acquisti esterni", default=False)
    external_purchases_cost = models.DecimalField(
        "Costo acquisti esterni", max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    external_work = models.BooleanField("Lavorazioni esterne", default=False)
    external_work_cost = models.DecimalField(
        "Costo lavorazioni esterne", max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    bureaucracy = models.BooleanField("Certificati e burocrazia", default=False)
    bureaucracy_cost = models.DecimalField(
        "Costo certificati e burocrazia", max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    feasibility_manually_set = models.BooleanField(default=False, editable=False)
    display_order = models.PositiveSmallIntegerField(default=1)
    creation_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        verbose_name = "articolo"
        verbose_name_plural = "storico articoli"
        ordering = ["display_order", "id"]
        indexes = [
            models.Index(fields=["code", "description"]),
            models.Index(fields=["code", "-article_date"], name="quoteitem_code_date_idx"),
            models.Index(fields=["code", "revision", "-article_date"], name="quoteitem_key_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1, quantity__lte=99999),
                name="item_quantity_positive",
            ),
            models.CheckConstraint(condition=models.Q(length_mm__isnull=True) | models.Q(length_mm__gt=0), name="item_length_positive"),
            models.CheckConstraint(condition=models.Q(height_mm__isnull=True) | models.Q(height_mm__gt=0), name="item_height_positive"),
            models.CheckConstraint(condition=models.Q(depth_mm__isnull=True) | models.Q(depth_mm__gt=0), name="item_depth_positive"),
        ]

    @property
    def dimensions_display(self) -> str:
        values = (("L", self.length_mm), ("A", self.height_mm), ("P", self.depth_mm))
        dimensions = " × ".join(
            f"{label} {format(value.normalize(), 'f').replace('.', ',')} mm"
            for label, value in values if value is not None
        )
        return dimensions or self.legacy_dimensions

    @property
    def material_cost(self) -> Decimal:
        return sum((row.total_cost or ZERO for row in self.materials.all()), ZERO)

    @property
    def total_cost(self) -> Decimal:
        return (
            self.material_cost
            + sum((phase.total_cost for phase in self.phases.filter(active=True)), ZERO)
            + self.supplementary_cost
        )

    @property
    def supplementary_cost(self) -> Decimal:
        values = (
            self.external_purchases_cost if self.external_purchases else ZERO,
            self.external_work_cost if self.external_work else ZERO,
            self.bureaucracy_cost if self.bureaucracy else ZERO,
        )
        return sum((value or ZERO for value in values), ZERO)

    @property
    def has_missing_material_cost(self) -> bool:
        return any(row.unit_cost_snapshot is None for row in self.materials.all())

    def __str__(self) -> str:
        return self.code


class ItemMaterial(models.Model):
    item = models.ForeignKey(QuoteItem, on_delete=models.CASCADE, related_name="materials")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, verbose_name="Materiale")
    weight_kg = models.DecimalField("Peso (kg) per pezzo", max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit_cost_snapshot = models.DecimalField("Costo acquisto/kg", max_digits=12, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(ZERO)])

    class Meta:
        verbose_name = "materiale articolo"
        verbose_name_plural = "materiali articolo"
        constraints = [
            models.UniqueConstraint(fields=["item", "material"], name="unique_material_per_item"),
            models.CheckConstraint(condition=models.Q(weight_kg__gt=0), name="material_weight_positive"),
        ]

    @property
    def total_cost(self) -> Decimal | None:
        if self.unit_cost_snapshot is None:
            return None
        return self.weight_kg * self.unit_cost_snapshot * self.item.quantity


class ItemPhase(models.Model):
    class InternalAnswer(models.TextChoices):
        YES = "yes", "Si"
        NO = "no", "No"
        TO_CHECK = "to_check", "Da verificare"

    item = models.ForeignKey(QuoteItem, on_delete=models.CASCADE, related_name="phases")
    definition = models.ForeignKey(PhaseDefinition, on_delete=models.PROTECT, related_name="item_phases")
    active = models.BooleanField("Fase attiva", default=False)
    notes = models.TextField("Note fase", blank=True)
    display_order = models.PositiveSmallIntegerField("Ordine", default=1)
    internal_answer = models.CharField("Si riesce a realizzare internamente?", max_length=20, choices=InternalAnswer.choices, default=InternalAnswer.TO_CHECK)

    class Meta:
        verbose_name = "fase articolo"
        verbose_name_plural = "fasi articolo"
        ordering = ["display_order"]
        constraints = [models.UniqueConstraint(fields=["item", "definition"], name="unique_phase_per_item")]

    @property
    def total_cost(self) -> Decimal:
        if not self.active:
            return ZERO
        return (
            sum((operation.total_cost for operation in self.operations.all()), ZERO)
            + sum((cost.amount for cost in self.direct_costs.all()), ZERO)
            + sum((treatment.cost for treatment in self.treatments.all()), ZERO)
        )


class TimeOperation(models.Model):
    class TimeBasis(models.TextChoices):
        PER_PIECE = "per_piece", "Per singolo pezzo"
        LOT = "lot", "Per intero lotto"

    phase = models.ForeignKey(ItemPhase, on_delete=models.CASCADE, related_name="operations")
    resource = models.ForeignKey(ProductionResource, on_delete=models.PROTECT, related_name="operations", verbose_name="Risorsa")
    working_minutes = models.DecimalField("Minuti lavorazione", max_digits=10, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    setup_minutes = models.DecimalField("Minuti attrezzaggio", max_digits=10, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)])
    operators_snapshot = models.PositiveSmallIntegerField("Operatori", validators=[MinValueValidator(1)])
    time_basis = models.CharField("Riferimento tempo", max_length=20, choices=TimeBasis.choices, default=TimeBasis.PER_PIECE)
    resource_name_snapshot = models.CharField("Nome risorsa acquisito", max_length=150)
    hourly_cost_snapshot = models.DecimalField("Costo orario acquisito", max_digits=12, decimal_places=4, validators=[MinValueValidator(ZERO)])
    notes = models.TextField("Note", blank=True)

    class Meta:
        verbose_name = "operazione temporale"
        verbose_name_plural = "operazioni temporali"
        constraints = [
            models.CheckConstraint(condition=models.Q(working_minutes__gte=0), name="working_minutes_non_negative"),
            models.CheckConstraint(condition=models.Q(setup_minutes__gte=0), name="setup_minutes_non_negative"),
            models.CheckConstraint(condition=models.Q(operators_snapshot__gte=1), name="operation_operators_positive"),
            models.CheckConstraint(condition=models.Q(hourly_cost_snapshot__gte=0), name="operation_cost_non_negative"),
        ]

    @property
    def total_cost(self) -> Decimal:
        from .services.calculations import calculate_time_cost
        return calculate_time_cost(
            working_minutes=self.working_minutes,
            setup_minutes=self.setup_minutes,
            hourly_cost=self.hourly_cost_snapshot,
            operators=self.operators_snapshot,
            quantity=self.phase.item.quantity,
            per_piece=self.time_basis == self.TimeBasis.PER_PIECE,
        )


class DirectCost(models.Model):
    phase = models.ForeignKey(ItemPhase, on_delete=models.CASCADE, related_name="direct_costs")
    description = models.CharField("Descrizione", max_length=250)
    supplier = models.CharField("Fornitore", max_length=150, blank=True)
    amount = models.DecimalField("Importo", max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    notes = models.TextField("Note", blank=True)

    class Meta:
        verbose_name = "costo diretto"
        verbose_name_plural = "costi diretti"
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name="direct_cost_non_negative")]


class ExternalTreatment(models.Model):
    class TreatmentType(models.TextChoices):
        GALVANIZING = "galvanizing", "Zincatura"
        CATAPHORESIS = "cataphoresis", "Cataforesi"
        PAINTING = "painting", "Verniciatura"
        OTHER = "other", "Altro"

    phase = models.ForeignKey(ItemPhase, on_delete=models.CASCADE, related_name="treatments")
    treatment_type = models.CharField("Tipo trattamento", max_length=20, choices=TreatmentType.choices)
    description = models.CharField("Descrizione", max_length=250, blank=True)
    supplier = models.CharField("Fornitore", max_length=150, blank=True)
    cost = models.DecimalField("Costo", max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)])
    notes = models.TextField("Note", blank=True)

    class Meta:
        verbose_name = "trattamento esterno"
        verbose_name_plural = "trattamenti esterni"
        constraints = [models.CheckConstraint(condition=models.Q(cost__gte=0), name="treatment_cost_non_negative")]

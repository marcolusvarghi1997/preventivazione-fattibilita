from decimal import Decimal
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower


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


class ClientContact(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts", verbose_name="Cliente")
    name = models.CharField("Nome referente", max_length=150, db_index=True)
    email = models.EmailField("Email", blank=True, db_index=True)
    phone = models.CharField("Telefono", max_length=50, blank=True)
    notes = models.TextField("Note", blank=True)
    active = models.BooleanField("Attivo", default=True)

    class Meta:
        verbose_name = "referente cliente"
        verbose_name_plural = "referenti clienti"
        ordering = ["client__name", "name", "email"]
        constraints = [
            models.UniqueConstraint(fields=["client", "name", "email"], name="unique_contact_per_client_email"),
            models.UniqueConstraint(
                models.F("client"),
                Lower("name"),
                name="unique_contact_name_per_client_ci",
            ),
            models.UniqueConstraint(
                models.F("client"),
                Lower("email"),
                condition=~models.Q(email=""),
                name="unique_contact_email_per_client_ci",
            ),
        ]

    def __str__(self) -> str:
        suffix = f" — {self.email}" if self.email else ""
        return f"{self.name}{suffix}"


hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Inserire un colore esadecimale nel formato #RRGGBB.",
)


class SiteConfiguration(models.Model):
    site_title = models.CharField("Titolo applicazione", max_length=100, default="Preventivazione e Fattibilità")
    company_name = models.CharField("Nome azienda", max_length=200, default="Officine Pollastri")
    address = models.TextField("Indirizzo", blank=True)
    vat = models.CharField("Partita IVA", max_length=30, blank=True)
    email = models.EmailField("Email azienda", blank=True)
    phone = models.CharField("Telefono azienda", max_length=50, blank=True)
    terms = models.TextField("Condizioni nei PDF cliente", blank=True, default="Validità e condizioni da definire.")
    logo = models.FileField("Logo header e PDF", upload_to="branding/", blank=True)
    favicon = models.FileField("Favicon", upload_to="branding/", blank=True)
    primary_color = models.CharField("Colore principale", max_length=7, default="#273A84", validators=[hex_color_validator])
    accent_color = models.CharField("Colore secondario", max_length=7, default="#00817D", validators=[hex_color_validator])
    updated_at = models.DateTimeField("Ultima modifica", auto_now=True)

    class Meta:
        verbose_name = "configurazione azienda e rete"
        verbose_name_plural = "configurazione azienda e rete"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return "Configurazione applicazione"


class LanDeviceAccess(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "In attesa"
        ALLOWED = "allowed", "Sì, autorizzato"
        DENIED = "denied", "No, bloccato"

    ip_address = models.GenericIPAddressField("Indirizzo IP", protocol="both", unpack_ipv4=True, unique=True)
    status = models.CharField("Accesso", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    first_seen_at = models.DateTimeField("Prima richiesta", auto_now_add=True)
    last_seen_at = models.DateTimeField("Ultima richiesta")
    request_count = models.PositiveIntegerField("Richieste rilevate", default=1)
    decided_at = models.DateTimeField("Ultima decisione", null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lan_access_decisions",
        verbose_name="Decisione di",
    )

    class Meta:
        verbose_name = "accesso dispositivo LAN"
        verbose_name_plural = "accessi dispositivi LAN"
        ordering = ("-last_seen_at", "ip_address")

    def __str__(self) -> str:
        return f"{self.ip_address} — {self.get_status_display()}"


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

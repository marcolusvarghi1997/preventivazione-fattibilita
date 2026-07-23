from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from apps.catalog.models import Client, ClientContact, Material, ProductionResource
from .formatting import format_decimal_it, normalize_decimal_input
from .models import DirectCost, ExternalTreatment, Feasibility, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


FEASIBILITY_UI_CHOICES = (
    (Feasibility.INTERNAL, Feasibility.INTERNAL.label),
    (Feasibility.TO_CHECK, Feasibility.TO_CHECK.label),
    (Feasibility.NOT_FEASIBLE, Feasibility.NOT_FEASIBLE.label),
)


class ItalianDecimalInput(forms.TextInput):
    def __init__(self, attrs=None, places=2):
        self.places = places
        defaults = {
            "inputmode": "decimal",
            "data-decimal-input": "",
            "data-decimal-places": str(places),
            "pattern": rf"[0-9]+([,.][0-9]{{1,{places}}})?",
        }
        defaults.update(attrs or {})
        super().__init__(defaults)

    def format_value(self, value):
        if value in (None, ""):
            return ""
        if isinstance(value, Decimal):
            return format_decimal_it(value, self.places)
        return value


class ItalianDecimalField(forms.DecimalField):
    default_error_messages = {**forms.DecimalField.default_error_messages, "invalid": "Inserire un numero valido."}

    def __init__(self, *args, display_places=None, **kwargs):
        places = display_places if display_places is not None else kwargs.get("decimal_places", 2)
        kwargs.setdefault("widget", ItalianDecimalInput(places=places))
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            return super().to_python(normalize_decimal_input(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError(self.error_messages["invalid"], code="invalid")


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or "%Y-%m-%d")


class QuoteGeneralForm(forms.ModelForm):
    client_lookup = forms.CharField(
        label="Cliente",
        required=False,
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "data-client-search": "",
            "placeholder": "Inizia a scrivere la ragione sociale",
            "role": "combobox",
            "aria-autocomplete": "list",
            "aria-controls": "client-results",
            "aria-expanded": "false",
        }),
    )
    contact_id = forms.IntegerField(required=False, widget=forms.HiddenInput(attrs={"data-contact-id": ""}))

    class Meta:
        model = Quote
        fields = ("date", "client", "client_contact", "client_email", "internal_notes", "customer_notes")
        widgets = {
            "date": DateInput(),
            "client": forms.HiddenInput(attrs={"data-client-id": ""}),
            "client_contact": forms.HiddenInput(attrs={"data-contact-name": ""}),
            "client_email": forms.HiddenInput(attrs={"data-contact-email": ""}),
            "internal_notes": forms.Textarea(attrs={"rows": 3}),
            "customer_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(active=True)
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        self.fields["client_contact"].required = False
        self.fields["client_email"].required = False
        if self.instance and self.instance.client_id:
            self.fields["client_lookup"].initial = self.instance.client.name
            saved_contact = ClientContact.objects.filter(
                client_id=self.instance.client_id,
                active=True,
                name__iexact=self.instance.client_contact,
                email__iexact=self.instance.client_email,
            ).first()
            if saved_contact:
                self.fields["contact_id"].initial = saved_contact.pk
        self.order_fields((
            "date", "client_lookup", "client", "contact_id", "client_contact", "client_email",
            "internal_notes", "customer_notes",
        ))

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        lookup = (cleaned.get("client_lookup") or "").strip()
        if lookup and not client:
            client = Client.objects.filter(active=True, name__iexact=lookup).first()
            if client:
                cleaned["client"] = client
            else:
                self.add_error("client_lookup", "Seleziona un cliente suggerito oppure registrane uno con il pulsante rapido.")
        if client and lookup and client.name.casefold() != lookup.casefold():
            self.add_error("client_lookup", "Il cliente scritto non corrisponde a quello selezionato.")
        contact_id = cleaned.get("contact_id")
        if contact_id:
            contact = ClientContact.objects.filter(pk=contact_id, client=client, active=True).first()
            if not contact:
                self.add_error("client_contact", "Il referente selezionato non appartiene al cliente indicato.")
            else:
                cleaned["client_contact"] = contact.name
                cleaned["client_email"] = contact.email
        elif client:
            cleaned["client_contact"] = ""
            cleaned["client_email"] = ""
        return cleaned


class QuoteSummaryForm(forms.ModelForm):
    offered_price = ItalianDecimalField(
        label="Prezzo commerciale offerto",
        required=False,
        min_value=Decimal("0"),
        max_digits=14,
        decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )

    class Meta:
        model = Quote
        fields = ("feasibility", "offered_price", "customer_decision")
        labels = {"feasibility": "Fattibilità"}
        widgets = {"feasibility": forms.RadioSelect()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["feasibility"].choices = FEASIBILITY_UI_CHOICES

    def save(self, commit=True):
        quote = super().save(commit=False)
        if quote.customer_decision == Quote.CustomerDecision.ACCEPTED:
            quote.status = Quote.Status.COMPLETED
        elif quote.customer_decision == Quote.CustomerDecision.REJECTED:
            quote.status = Quote.Status.REJECTED
        elif quote.status == Quote.Status.REJECTED:
            quote.status = Quote.Status.DRAFT
        if commit:
            quote.save()
        return quote


class QuoteItemForm(forms.ModelForm):
    external_purchases_cost = ItalianDecimalField(
        label="Costo acquisti esterni", required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0", "data-extra-cost": "external_purchases_cost"}, places=2),
    )
    external_work_cost = ItalianDecimalField(
        label="Costo lavorazioni esterne", required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0", "data-extra-cost": "external_work_cost"}, places=2),
    )
    bureaucracy_cost = ItalianDecimalField(
        label="Costo certificati e burocrazia", required=False, min_value=Decimal("0"), max_digits=14, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0", "data-extra-cost": "bureaucracy_cost"}, places=2),
    )

    class Meta:
        model = QuoteItem
        fields = (
            "code", "quantity", "description", "revision", "dimensions", "technical_notes", "feasibility",
            "external_purchases", "external_purchases_cost", "external_work", "external_work_cost",
            "bureaucracy", "bureaucracy_cost",
        )
        labels = {"quantity": "Quantità", "feasibility": "Fattibilità articolo"}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "technical_notes": forms.Textarea(attrs={"rows": 3}),
            "quantity": forms.NumberInput(attrs={"min": 1}),
            "feasibility": forms.RadioSelect(),
            "external_purchases": forms.CheckboxInput(attrs={"data-extra-toggle": "external_purchases_cost"}),
            "external_work": forms.CheckboxInput(attrs={"data-extra-toggle": "external_work_cost"}),
            "bureaucracy": forms.CheckboxInput(attrs={"data-extra-toggle": "bureaucracy_cost"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["feasibility"].choices = FEASIBILITY_UI_CHOICES
        self.fields["quantity"].min_value = 1
        self.fields["quantity"].widget.attrs["min"] = "1"

    def clean(self):
        cleaned = super().clean()
        for toggle, cost in (
            ("external_purchases", "external_purchases_cost"),
            ("external_work", "external_work_cost"),
            ("bureaucracy", "bureaucracy_cost"),
        ):
            if not cleaned.get(toggle):
                cleaned[cost] = getattr(self.instance, cost, None) if self.instance.pk else cleaned.get(cost)
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        item.feasibility_manually_set = item.feasibility != Feasibility.TO_CHECK
        if commit:
            item.save()
        return item


class ItemMaterialForm(forms.ModelForm):
    weight_kg = ItalianDecimalField(
        label="Peso (kg) per pezzo", min_value=Decimal("0.001"), max_digits=12, decimal_places=3,
        widget=ItalianDecimalInput(attrs={"min": "0.001"}, places=3),
    )
    unit_cost_snapshot = ItalianDecimalField(
        label="Costo acquisto/kg", required=False, min_value=Decimal("0"), max_digits=12, decimal_places=4,
        display_places=2, widget=ItalianDecimalInput(attrs={"min": "0", "data-material-cost": ""}, places=2),
    )

    class Meta:
        model = ItemMaterial
        fields = ("material", "weight_kg", "unit_cost_snapshot")
        labels = {"unit_cost_snapshot": "Costo acquisto/kg"}
        widgets = {
            "material": forms.Select(attrs={"data-material-select": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(active=True)
        self.fields["unit_cost_snapshot"].required = False


class ItemMaterialEditForm(forms.ModelForm):
    weight_kg = ItalianDecimalField(
        label="Peso (kg) per pezzo", min_value=Decimal("0.001"), max_digits=12, decimal_places=3,
        widget=ItalianDecimalInput(attrs={"min": "0.001"}, places=3),
    )
    unit_cost_snapshot = ItalianDecimalField(
        label="Costo acquisto/kg", required=False, min_value=Decimal("0"), max_digits=12, decimal_places=4,
        display_places=2, widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )

    class Meta:
        model = ItemMaterial
        fields = ("weight_kg", "unit_cost_snapshot")
        labels = {"unit_cost_snapshot": "Costo acquisto/kg"}


class PhaseForm(forms.ModelForm):
    class Meta:
        model = ItemPhase
        fields = ("active",)
        widgets = {"active": forms.CheckboxInput(attrs={"data-phase-toggle": "", "aria-label": "Sì, attiva"})}


class TimeOperationForm(forms.ModelForm):
    working_minutes = ItalianDecimalField(
        label="Minuti lavorazione", min_value=Decimal("0"), max_digits=10, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )
    setup_minutes = ItalianDecimalField(
        label="Minuti attrezzaggio", min_value=Decimal("0"), max_digits=10, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )

    class Meta:
        model = TimeOperation
        fields = ("resource", "working_minutes", "setup_minutes", "operators_snapshot", "time_basis", "notes")
        widgets = {
            "operators_snapshot": forms.NumberInput(attrs={"min": 1}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, phase=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = phase
        self.fields["operators_snapshot"].min_value = 1
        self.fields["operators_snapshot"].widget.attrs["min"] = "1"
        if phase:
            resources = ProductionResource.objects.filter(phase=phase.definition, active=True)
            self.fields["resource"].queryset = resources
            if resources.count() == 1 and not resources.first().user_selectable:
                self.fields["resource"].initial = resources.first()
                self.fields["resource"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        resource = cleaned.get("resource")
        if resource and self.phase and resource.phase_id != self.phase.definition_id:
            raise ValidationError("La risorsa selezionata non appartiene a questa fase.")
        if cleaned.get("working_minutes", 0) == 0 and cleaned.get("setup_minutes", 0) == 0:
            raise ValidationError("Inserire almeno un tempo maggiore di zero.")
        return cleaned


class DirectCostForm(forms.ModelForm):
    amount = ItalianDecimalField(
        label="Importo", min_value=Decimal("0"), max_digits=14, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )

    class Meta:
        model = DirectCost
        fields = ("description", "supplier", "amount", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, phase=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].required = False
        self.fields["amount"].label = "Importo opzionale"
        if phase and phase.definition.code == "lavorazioni-extra":
            self.fields.pop("supplier")
            self.fields["description"].label = "Lavorazione interna extra"

    def clean_amount(self):
        return self.cleaned_data.get("amount") or Decimal("0")


class TreatmentForm(forms.ModelForm):
    cost = ItalianDecimalField(
        label="Costo", min_value=Decimal("0"), max_digits=14, decimal_places=2,
        widget=ItalianDecimalInput(attrs={"min": "0"}, places=2),
    )

    class Meta:
        model = ExternalTreatment
        fields = ("treatment_type", "description", "supplier", "cost", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("treatment_type") == ExternalTreatment.TreatmentType.OTHER and not (cleaned.get("description") or "").strip():
            self.add_error("description", "La descrizione e obbligatoria per il tipo Altro.")
        return cleaned


class QuoteSearchForm(forms.Form):
    q = forms.CharField(label="Numero, codice, cliente o descrizione", required=False)
    status = forms.ChoiceField(label="Stato", required=False, choices=(
        ("", "Tutti"),
        (Quote.Status.DRAFT, "Bozza"),
        (Quote.Status.COMPLETED, "Completato"),
        (Quote.Status.REJECTED, "Rifiutato"),
    ))
    feasibility = forms.ChoiceField(label="Fattibilità", required=False, choices=(("", "Tutte"), *Feasibility.choices))
    date_from = forms.DateField(label="Dal", required=False, widget=DateInput())
    date_to = forms.DateField(label="Al", required=False, widget=DateInput())


class QuickClientForm(forms.ModelForm):
    contact_name = forms.CharField(label="Primo referente", max_length=150, required=False)
    contact_email = forms.EmailField(label="Email referente", required=False)
    contact_phone = forms.CharField(label="Telefono referente", max_length=50, required=False)

    class Meta:
        model = Client
        fields = ("name", "email", "phone", "address")
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}

    def save(self, commit=True):
        client = super().save(commit=commit)
        if commit and self.cleaned_data.get("contact_name"):
            ClientContact.objects.create(
                client=client,
                name=self.cleaned_data["contact_name"],
                email=self.cleaned_data.get("contact_email", ""),
                phone=self.cleaned_data.get("contact_phone", ""),
            )
        return client


class QuickClientContactForm(forms.ModelForm):
    class Meta:
        model = ClientContact
        fields = ("client", "name", "email", "phone")
        widgets = {
            "client": forms.HiddenInput(attrs={"data-quick-contact-client": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(active=True)

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        name = (cleaned.get("name") or "").strip()
        email = (cleaned.get("email") or "").strip()
        if not client:
            return cleaned
        contacts = ClientContact.objects.filter(client=client)
        if name and contacts.filter(name__iexact=name).exists():
            self.add_error("name", "Esiste già un referente con questo nome per il cliente selezionato.")
        if email and contacts.filter(email__iexact=email).exists():
            self.add_error("email", "Questa email è già associata a un referente del cliente selezionato.")
        return cleaned

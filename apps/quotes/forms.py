from django import forms
from django.core.exceptions import ValidationError
from apps.catalog.models import Client, Material, ProductionResource
from .models import DirectCost, ExternalTreatment, Feasibility, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or "%Y-%m-%d")


class QuoteGeneralForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ("date", "client", "client_contact", "internal_notes", "customer_notes")
        widgets = {"date": DateInput(), "internal_notes": forms.Textarea(attrs={"rows": 3}), "customer_notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(active=True)
        self.fields["date"].input_formats = ["%Y-%m-%d"]


class QuoteSummaryForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ("feasibility", "offered_price")
        widgets = {"offered_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"})}


class QuoteItemForm(forms.ModelForm):
    class Meta:
        model = QuoteItem
        fields = ("code", "quantity", "description", "revision", "dimensions", "technical_notes", "feasibility")
        widgets = {"technical_notes": forms.Textarea(attrs={"rows": 3}), "quantity": forms.NumberInput(attrs={"min": 1})}

    def save(self, commit=True):
        item = super().save(commit=False)
        item.feasibility_manually_set = item.feasibility != Feasibility.TO_CHECK
        if commit:
            item.save()
        return item


class ItemMaterialForm(forms.ModelForm):
    class Meta:
        model = ItemMaterial
        fields = ("material", "weight_kg")
        widgets = {"weight_kg": forms.NumberInput(attrs={"min": "0.001", "step": "0.001"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(active=True)


class PhaseForm(forms.ModelForm):
    class Meta:
        model = ItemPhase
        fields = ("active", "notes", "internal_answer")
        widgets = {"active": forms.RadioSelect(choices=((True, "Si, attiva"), (False, "No, non attiva"))), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.definition_id and self.instance.definition.code != "acquisti-esterni":
            self.fields.pop("internal_answer")


class TimeOperationForm(forms.ModelForm):
    class Meta:
        model = TimeOperation
        fields = ("resource", "working_minutes", "setup_minutes", "operators_snapshot", "time_basis", "notes")
        widgets = {
            "working_minutes": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "setup_minutes": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "operators_snapshot": forms.NumberInput(attrs={"min": 1}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, phase=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = phase
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
    class Meta:
        model = DirectCost
        fields = ("description", "supplier", "amount", "notes")
        widgets = {"amount": forms.NumberInput(attrs={"min": 0, "step": "0.01"}), "notes": forms.Textarea(attrs={"rows": 2})}


class TreatmentForm(forms.ModelForm):
    class Meta:
        model = ExternalTreatment
        fields = ("treatment_type", "description", "supplier", "cost", "notes")
        widgets = {"cost": forms.NumberInput(attrs={"min": 0, "step": "0.01"}), "notes": forms.Textarea(attrs={"rows": 2})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("treatment_type") == ExternalTreatment.TreatmentType.OTHER and not (cleaned.get("description") or "").strip():
            self.add_error("description", "La descrizione e obbligatoria per il tipo Altro.")
        return cleaned


class QuoteSearchForm(forms.Form):
    q = forms.CharField(label="Numero, codice, cliente o descrizione", required=False)
    status = forms.ChoiceField(label="Stato", required=False, choices=(("", "Tutti"), *Quote.Status.choices))
    feasibility = forms.ChoiceField(label="Fattibilita", required=False, choices=(("", "Tutte"), *Feasibility.choices))
    date_from = forms.DateField(label="Dal", required=False, widget=DateInput())
    date_to = forms.DateField(label="Al", required=False, widget=DateInput())

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    DirectCostForm, ItemMaterialForm, PhaseForm, QuoteGeneralForm, QuoteItemForm,
    QuoteSearchForm, QuoteSummaryForm, TimeOperationForm, TreatmentForm,
)
from .models import DirectCost, ExternalTreatment, Feasibility, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from .phases import phase_registry
from .services.quotes import duplicate_quote, initialize_item_phases
from .services.validation import validate_quote


def quote_queryset():
    return Quote.objects.select_related("client", "author").prefetch_related(
        "items__materials__material", "items__phases__definition",
        "items__phases__operations__resource", "items__phases__direct_costs", "items__phases__treatments",
    )


def get_quote(pk: int) -> Quote:
    return get_object_or_404(quote_queryset(), pk=pk)


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def dashboard(request: HttpRequest) -> HttpResponse:
    quotes = quote_queryset().exclude(status=Quote.Status.ARCHIVED)[:12]
    return render(request, "quotes/dashboard.html", {"quotes": quotes})


@login_required
@permission_required("quotes.add_quote", raise_exception=True)
def quote_general(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    quote = get_quote(pk) if pk else None
    if quote and not request.user.has_perm("quotes.change_quote"):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    form = QuoteGeneralForm(request.POST or None, instance=quote)
    if request.method == "POST" and form.is_valid():
        quote = form.save(commit=False)
        if not quote.pk:
            quote.author = request.user
        quote.save()
        messages.success(request, "Dati generali salvati.")
        return redirect("quotes:items", pk=quote.pk)
    return render(request, "quotes/general.html", {"form": form, "quote": quote, "step": 1})


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_items(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    return render(request, "quotes/items.html", {
        "quote": quote, "item_form": QuoteItemForm(), "material_form": ItemMaterialForm(), "step": 2,
    })


@login_required
@permission_required("quotes.add_quoteitem", raise_exception=True)
@require_POST
def item_add(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    form = QuoteItemForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            item = form.save(commit=False)
            item.quote = quote
            item.display_order = quote.items.count() + 1
            item.save()
            initialize_item_phases(item)
        messages.success(request, f"Articolo {item.code} aggiunto. Ora aggiungi almeno un materiale.")
    else:
        messages.error(request, "Articolo non aggiunto: controllare i campi indicati.")
        return render(request, "quotes/items.html", {"quote": get_quote(pk), "item_form": form, "material_form": ItemMaterialForm(), "step": 2}, status=422)
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.change_quoteitem", raise_exception=True)
def item_edit(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    quote = get_quote(pk)
    item = get_object_or_404(QuoteItem, pk=item_id, quote=quote)
    form = QuoteItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Articolo aggiornato.")
        return redirect("quotes:items", pk=pk)
    return render(request, "quotes/item_edit.html", {"quote": quote, "item": item, "form": form, "step": 2})


@login_required
@permission_required("quotes.delete_quoteitem", raise_exception=True)
@require_POST
def item_delete(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    item = get_object_or_404(QuoteItem, pk=item_id, quote_id=pk)
    code = item.code
    item.delete()
    messages.success(request, f"Articolo {code} rimosso.")
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.add_itemmaterial", raise_exception=True)
@require_POST
def material_add(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    item = get_object_or_404(QuoteItem, pk=item_id, quote_id=pk)
    form = ItemMaterialForm(request.POST)
    if form.is_valid():
        material = form.cleaned_data["material"]
        if item.materials.filter(material=material).exists():
            messages.error(request, "Questo materiale e gia presente nell'articolo.")
        else:
            row = form.save(commit=False)
            row.item = item
            row.unit_cost_snapshot = material.current_cost_per_kg
            row.save()
            messages.success(request, "Materiale aggiunto con il costo corrente acquisito.")
    else:
        messages.error(request, "Materiale non aggiunto: verificare materiale e peso.")
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.delete_itemmaterial", raise_exception=True)
@require_POST
def material_delete(request: HttpRequest, pk: int, material_id: int) -> HttpResponse:
    row = get_object_or_404(ItemMaterial, pk=material_id, item__quote_id=pk)
    row.delete()
    messages.success(request, "Materiale rimosso.")
    return redirect("quotes:items", pk=pk)


def build_phase_rows(quote: Quote):
    rows = []
    for item in quote.items.all():
        if item.phases.count() < len(phase_registry):
            initialize_item_phases(item)
        phases = []
        for phase in item.phases.all():
            config = phase_registry[phase.definition.code]
            operation_form = TimeOperationForm(phase=phase, prefix=f"op-{phase.pk}", initial={"operators_snapshot": 1})
            fixed_resource = operation_form.fields["resource"].queryset.first()
            if fixed_resource and operation_form.fields["resource"].queryset.count() == 1:
                operation_form.fields["operators_snapshot"].initial = fixed_resource.default_operators
            phases.append({
                "phase": phase, "config": config, "phase_form": PhaseForm(instance=phase, prefix=f"phase-{phase.pk}"),
                "operation_form": operation_form, "direct_form": DirectCostForm(prefix=f"cost-{phase.pk}"),
                "treatment_form": TreatmentForm(prefix=f"treat-{phase.pk}"),
            })
        rows.append({"item": item, "phases": phases})
    return rows


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_work(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    return render(request, "quotes/work.html", {"quote": quote, "item_rows": build_phase_rows(quote), "step": 3})


@login_required
@permission_required("quotes.change_itemphase", raise_exception=True)
@require_POST
def phase_update(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    phase = get_object_or_404(ItemPhase, pk=phase_id, item__quote_id=pk)
    form = PhaseForm(request.POST, instance=phase, prefix=f"phase-{phase.pk}")
    if form.is_valid():
        phase = form.save()
        if phase.definition.code == "acquisti-esterni" and phase.internal_answer == ItemPhase.InternalAnswer.NO and phase.direct_costs.filter(amount__gt=0).exists() and not phase.item.feasibility_manually_set:
            phase.item.feasibility = Feasibility.EXTERNAL
            phase.item.save(update_fields=["feasibility"])
        messages.success(request, f"Fase {phase.definition.name} salvata.")
    else:
        messages.error(request, "Fase non salvata: controllare i dati.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_timeoperation", raise_exception=True)
@require_POST
def operation_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    phase = get_object_or_404(ItemPhase.objects.select_related("definition", "item"), pk=phase_id, item__quote_id=pk)
    config = phase_registry[phase.definition.code]
    form = TimeOperationForm(request.POST, phase=phase, prefix=f"op-{phase.pk}")
    if not config.multiple_rows and phase.operations.exists():
        messages.error(request, "Questa fase prevede una sola operazione. Rimuovere quella esistente per sostituirla.")
    elif form.is_valid():
        operation = form.save(commit=False)
        resource = form.cleaned_data["resource"]
        operation.phase = phase
        operation.resource_name_snapshot = resource.name
        operation.hourly_cost_snapshot = resource.hourly_cost_per_person
        operation.save()
        phase.active = True
        phase.save(update_fields=["active"])
        messages.success(request, "Operazione aggiunta e costo ricalcolato.")
    else:
        messages.error(request, "Operazione non aggiunta: " + " ".join(str(e) for e in form.non_field_errors()))
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.delete_timeoperation", raise_exception=True)
@require_POST
def operation_delete(request: HttpRequest, pk: int, operation_id: int) -> HttpResponse:
    operation = get_object_or_404(TimeOperation, pk=operation_id, phase__item__quote_id=pk)
    operation.delete()
    messages.success(request, "Operazione rimossa.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_directcost", raise_exception=True)
@require_POST
def direct_cost_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    phase = get_object_or_404(ItemPhase, pk=phase_id, item__quote_id=pk)
    if phase.definition.code not in {"lavorazioni-extra", "acquisti-esterni"}:
        messages.error(request, "Questa fase non accetta costi diretti.")
    else:
        form = DirectCostForm(request.POST, prefix=f"cost-{phase.pk}")
        if form.is_valid():
            row = form.save(commit=False)
            row.phase = phase
            row.save()
            phase.active = True
            phase.save(update_fields=["active"])
            if phase.definition.code == "acquisti-esterni" and phase.internal_answer == ItemPhase.InternalAnswer.NO and row.amount > 0 and not phase.item.feasibility_manually_set:
                phase.item.feasibility = Feasibility.EXTERNAL
                phase.item.save(update_fields=["feasibility"])
            messages.success(request, "Costo aggiunto.")
        else:
            messages.error(request, "Costo non aggiunto: controllare descrizione e importo.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.delete_directcost", raise_exception=True)
@require_POST
def direct_cost_delete(request: HttpRequest, pk: int, cost_id: int) -> HttpResponse:
    get_object_or_404(DirectCost, pk=cost_id, phase__item__quote_id=pk).delete()
    messages.success(request, "Costo rimosso.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_externaltreatment", raise_exception=True)
@require_POST
def treatment_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    phase = get_object_or_404(ItemPhase, pk=phase_id, item__quote_id=pk, definition__code="trattamento-esterno")
    form = TreatmentForm(request.POST, prefix=f"treat-{phase.pk}")
    if form.is_valid():
        row = form.save(commit=False)
        row.phase = phase
        row.save()
        phase.active = True
        phase.save(update_fields=["active"])
        messages.success(request, "Trattamento aggiunto.")
    else:
        messages.error(request, "Trattamento non aggiunto: controllare i campi indicati.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.delete_externaltreatment", raise_exception=True)
@require_POST
def treatment_delete(request: HttpRequest, pk: int, treatment_id: int) -> HttpResponse:
    get_object_or_404(ExternalTreatment, pk=treatment_id, phase__item__quote_id=pk).delete()
    messages.success(request, "Trattamento rimosso.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_summary(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    form = QuoteSummaryForm(request.POST or None, instance=quote)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Riepilogo economico e fattibilita salvati.")
        return redirect("quotes:summary", pk=pk)
    result = validate_quote(quote)
    return render(request, "quotes/summary.html", {"quote": quote, "form": form, "validation": result, "step": 4})


@login_required
@permission_required("quotes.change_quote", raise_exception=True)
@require_POST
def quote_complete(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    result = validate_quote(quote)
    if result.can_complete:
        quote.status = Quote.Status.COMPLETED
        quote.save(update_fields=["status", "updated_at"])
        messages.success(request, "Preventivo segnato come completato.")
    else:
        messages.error(request, "Il preventivo non puo essere completato: correggere gli errori bloccanti.")
    return redirect("quotes:summary", pk=pk)


@login_required
@permission_required("quotes.duplicate_quote", raise_exception=True)
@require_POST
def quote_duplicate(request: HttpRequest, pk: int) -> HttpResponse:
    duplicate = duplicate_quote(get_quote(pk), request.user)
    messages.success(request, f"Preventivo duplicato: {duplicate.number}.")
    return redirect("quotes:general", pk=duplicate.pk)


@login_required
@permission_required("quotes.archive_quote", raise_exception=True)
@require_POST
def quote_archive(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(pk)
    quote.status = Quote.Status.ARCHIVED
    quote.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Preventivo {quote.number} archiviato. Nessun dato e stato cancellato.")
    return redirect("quotes:dashboard")


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_search(request: HttpRequest) -> HttpResponse:
    form = QuoteSearchForm(request.GET or None)
    queryset = quote_queryset()
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            term = data["q"]
            queryset = queryset.filter(Q(number__icontains=term) | Q(client__name__icontains=term) | Q(items__code__icontains=term) | Q(items__description__icontains=term)).distinct()
        if data["status"]:
            queryset = queryset.filter(status=data["status"])
        if data["feasibility"]:
            queryset = queryset.filter(feasibility=data["feasibility"])
        if data["date_from"]:
            queryset = queryset.filter(date__gte=data["date_from"])
        if data["date_to"]:
            queryset = queryset.filter(date__lte=data["date_to"])
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(request, "quotes/search.html", {"form": form, "page": page})

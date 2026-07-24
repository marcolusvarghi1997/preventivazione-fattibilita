from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Min, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    ArticleLoadForm, DirectCostForm, ItemMaterialEditForm, ItemMaterialForm, PhaseForm, QuickClientForm,
    QuickClientContactForm, QuoteGeneralForm, QuoteItemForm, QuoteSearchForm, QuoteSummaryForm,
    TimeOperationForm, TreatmentForm,
)
from apps.catalog.models import Client, ClientContact, Material
from .models import DirectCost, ExternalTreatment, Feasibility, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from .phases import phase_registry
from .services.quotes import (
    ArticleVersionConflict,
    archive_quotes,
    create_article_version_from_latest,
    duplicate_item,
    duplicate_quote,
    initialize_item_phases,
    latest_article_version,
    restore_quotes,
    search_latest_article_versions,
)
from .services.validation import validate_quote


def quote_queryset(user=None):
    queryset = Quote.objects.select_related("client", "author").prefetch_related(
        "items__materials__material", "items__phases__definition",
        "items__phases__operations__resource", "items__phases__direct_costs", "items__phases__treatments",
    )
    if user is not None and not user.is_superuser:
        queryset = queryset.filter(author=user)
    return queryset


def apply_quote_filters(queryset, data):
    if data["q"]:
        term = data["q"]
        queryset = queryset.filter(
            Q(number__icontains=term)
            | Q(client__name__icontains=term)
            | Q(items__code__icontains=term)
            | Q(items__description__icontains=term)
        ).distinct()
    if data["status"]:
        if data["status"] == Quote.Status.DRAFT:
            queryset = queryset.filter(
                status=Quote.Status.DRAFT,
                customer_decision=Quote.CustomerDecision.PENDING,
            )
        elif data["status"] == Quote.Status.COMPLETED:
            queryset = queryset.exclude(status=Quote.Status.ARCHIVED).filter(
                Q(status=Quote.Status.COMPLETED)
                | Q(customer_decision=Quote.CustomerDecision.ACCEPTED)
            )
        elif data["status"] == Quote.Status.REJECTED:
            queryset = queryset.exclude(status=Quote.Status.ARCHIVED).filter(
                Q(status=Quote.Status.REJECTED)
                | Q(customer_decision=Quote.CustomerDecision.REJECTED)
            )
        else:
            queryset = queryset.filter(status=data["status"])
    if data["feasibility"]:
        queryset = queryset.filter(feasibility=data["feasibility"])
    if data["date_from"]:
        queryset = queryset.filter(date__gte=data["date_from"])
    if data["date_to"]:
        queryset = queryset.filter(date__lte=data["date_to"])
    return queryset


def sort_quotes(queryset, request, fields):
    sort = request.GET.get("sort", "date")
    direction = request.GET.get("dir", "desc")
    if sort not in fields:
        sort = "date"
    if direction not in {"asc", "desc"}:
        direction = "desc"
    field = fields[sort]
    if field == "article_code":
        queryset = queryset.annotate(article_code=Min("items__code"))
    prefix = "-" if direction == "desc" else ""
    return queryset.order_by(f"{prefix}{field}", f"{prefix}id"), sort, direction


def get_quote(request: HttpRequest, pk: int) -> Quote:
    return get_object_or_404(quote_queryset(request.user), pk=pk)


def record_workflow_step(quote: Quote, step: int) -> None:
    if quote.last_workflow_step != step:
        Quote.objects.filter(pk=quote.pk).update(last_workflow_step=step)
        quote.last_workflow_step = step


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_resume(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    if (
        quote.status in {Quote.Status.COMPLETED, Quote.Status.REJECTED, Quote.Status.SENT, Quote.Status.ARCHIVED}
        or quote.customer_decision != Quote.CustomerDecision.PENDING
    ):
        return redirect("quotes:summary", pk=pk)
    if not quote.items.exists():
        return redirect("quotes:items", pk=pk)
    route = {1: "quotes:general", 2: "quotes:items", 3: "quotes:work", 4: "quotes:summary"}
    return redirect(route.get(quote.last_workflow_step, "quotes:items"), pk=pk)


def editable_quote_required(view_func):
    """Reject writes to archived quotes while keeping their data readable."""
    @wraps(view_func)
    def wrapped(request: HttpRequest, *args, **kwargs):
        pk = kwargs.get("pk")
        if request.method != "GET" and pk and get_quote(request, pk).status == Quote.Status.ARCHIVED:
            messages.error(
                request,
                "Il preventivo e archiviato e non puo essere modificato. Duplicalo per creare una nuova bozza modificabile.",
            )
            return redirect("quotes:summary", pk=pk)
        return view_func(request, *args, **kwargs)

    return wrapped


def form_error_summary(form) -> str:
    details = []
    for field_name, errors in form.errors.items():
        label = "Dati inseriti" if field_name == "__all__" else form.fields[field_name].label
        details.append(f"{label}: {' '.join(errors)}")
    return " ".join(details)


def build_item_rows(quote: Quote, *, item_override=None, material_override=None):
    rows = []
    for item in quote.items.all():
        item_form = item_override if item_override and item_override.instance.pk == item.pk else QuoteItemForm(
            instance=item, prefix=f"item-{item.pk}"
        )
        material_form = material_override if material_override and material_override.prefix == f"material-{item.pk}" else ItemMaterialForm(
            prefix=f"material-{item.pk}"
        )
        materials = []
        for row in item.materials.all():
            edit_form = ItemMaterialEditForm(instance=row, prefix=f"material-edit-{row.pk}")
            for field in edit_form.fields.values():
                field.widget.attrs["form"] = f"material-form-{row.pk}"
            materials.append({"row": row, "form": edit_form})
        rows.append({"item": item, "item_form": item_form, "material_form": material_form, "materials": materials})
    return rows


def render_items(
    request,
    quote,
    *,
    item_form=None,
    material_form=None,
    draft_load_form=None,
    open_item_id=None,
    status=200,
):
    return render(request, "quotes/items.html", {
        "quote": quote,
        "item_rows": build_item_rows(quote, item_override=item_form, material_override=material_form),
        "article_load_form": draft_load_form or ArticleLoadForm(),
        "show_draft": bool(draft_load_form),
        "open_item_id": open_item_id,
        "material_costs": {
            str(material.pk): str(material.current_cost_per_kg) if material.current_cost_per_kg is not None else ""
            for material in Material.objects.filter(active=True)
        },
        "step": 2,
    }, status=status)


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def dashboard(request: HttpRequest) -> HttpResponse:
    queryset = quote_queryset(request.user).exclude(status=Quote.Status.ARCHIVED)
    queryset, sort, direction = sort_quotes(queryset, request, {
        "number": "number", "client": "client__name", "date": "date",
        "status": "status", "feasibility": "feasibility", "price": "offered_price",
    })
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "quotes/dashboard.html",
        {
            "quotes": page.object_list, "page": page, "sort": sort, "direction": direction,
            "dashboard_query": query_params.urlencode(),
        },
    )


@login_required
@permission_required("quotes.add_quote", raise_exception=True)
@editable_quote_required
def quote_general(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    quote = get_quote(request, pk) if pk else None
    if quote and not request.user.has_perm("quotes.change_quote"):
        raise PermissionDenied
    if quote and request.method == "GET":
        record_workflow_step(quote, 1)
    form = QuoteGeneralForm(request.POST or None, instance=quote)
    if request.method == "POST" and form.is_valid():
        quote = form.save(commit=False)
        if not quote.pk:
            quote.author = request.user
        quote.last_workflow_step = 2
        quote.save()
        return redirect("quotes:items", pk=quote.pk)
    contacts = list(ClientContact.objects.filter(active=True, client__active=True).values(
        "id", "client_id", "name", "email", "preferred"
    ))
    return render(request, "quotes/general.html", {
        "form": form,
        "quote": quote,
        "step": 1,
        "clients": list(Client.objects.filter(active=True).values("id", "name", "email", "phone")),
        "contacts": contacts,
        "quick_client_form": QuickClientForm(prefix="quick-client"),
        "quick_contact_form": QuickClientContactForm(prefix="quick-contact"),
    })


@login_required
@permission_required("catalog.add_client", raise_exception=True)
@require_POST
def client_quick_add(request: HttpRequest) -> JsonResponse:
    form = QuickClientForm(request.POST, prefix="quick-client")
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": {name: list(errors) for name, errors in form.errors.items()}},
            status=422,
        )
    client = form.save()
    contact = client.contacts.first()
    return JsonResponse({
        "ok": True,
        "client": {"id": client.pk, "name": client.name, "email": client.email, "phone": client.phone},
        "contact": (
            {"id": contact.pk, "name": contact.name, "email": contact.email, "preferred": contact.preferred}
            if contact else None
        ),
    })


@login_required
@permission_required("catalog.add_clientcontact", raise_exception=True)
@require_POST
def client_contact_quick_add(request: HttpRequest) -> JsonResponse:
    form = QuickClientContactForm(request.POST, prefix="quick-contact")
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": {name: list(errors) for name, errors in form.errors.items()}},
            status=422,
        )
    try:
        contact = form.save()
    except IntegrityError:
        return JsonResponse(
            {"ok": False, "errors": {"name": ["Il referente risulta già registrato per questo cliente."]}},
            status=422,
        )
    return JsonResponse({
        "ok": True,
        "contact": {
            "id": contact.pk,
            "client_id": contact.client_id,
            "name": contact.name,
            "email": contact.email,
            "phone": contact.phone,
            "preferred": contact.preferred,
        },
    })


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_items(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    record_workflow_step(quote, 2)
    open_item_id = request.GET.get("open_item")
    return render_items(
        request,
        quote,
        open_item_id=int(open_item_id) if open_item_id and open_item_id.isdigit() else None,
    )


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
@require_GET
def item_latest_version(request: HttpRequest, pk: int) -> JsonResponse:
    quote = get_quote(request, pk)
    code = (request.GET.get("code") or "").strip()
    if not code:
        return JsonResponse({"ok": True, "results": []})
    added_keys = set(quote.items.values_list("code", "revision"))
    results = []
    for item in search_latest_article_versions(code=code):
        results.append({
            "id": item.pk,
            "code": item.code,
            "revision": item.revision,
            "article_date": item.article_date.isoformat(),
            "article_date_display": item.article_date.strftime("%d/%m/%Y"),
            "already_added": (item.code, item.revision) in added_keys,
        })
    return JsonResponse({"ok": True, "results": results})


@login_required
@permission_required("quotes.add_quoteitem", raise_exception=True)
@require_POST
@editable_quote_required
def item_add(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    form = ArticleLoadForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Articolo non caricato: controllare codice e revisione.")
        return render_items(
            request, get_quote(request, pk), draft_load_form=form, status=422
        )
    code = form.cleaned_data["code"]
    revision = (form.cleaned_data.get("revision") or "").strip()
    source_version_id = form.cleaned_data.get("source_version_id")
    creation_token = form.cleaned_data.get("creation_token")

    if creation_token:
        existing_for_token = QuoteItem.objects.filter(creation_token=creation_token).first()
        if existing_for_token:
            if existing_for_token.quote_id == quote.pk:
                messages.info(request, f"Articolo {existing_for_token.code} già aggiunto; il doppio invio è stato ignorato.")
                return redirect("quotes:items", pk=pk)
            form.add_error(None, "La richiesta di creazione non è valida. Ricarica la pagina e riprova.")

    if not form.errors and source_version_id:
        try:
            item, created = create_article_version_from_latest(
                code=code,
                quote=quote,
                revision=revision,
                creation_token=creation_token,
                expected_source_id=source_version_id,
            )
        except ArticleVersionConflict as exc:
            form.add_error("code", str(exc))
        else:
            if not created:
                messages.info(request, f"Articolo {item.code} già aggiunto; il doppio invio è stato ignorato.")
            return redirect("quotes:items", pk=pk)

    if not form.errors and latest_article_version(code, revision) is not None:
        form.add_error("code", "Articolo già presente. Seleziona il risultato corrispondente e usa Carica articolo.")

    if not form.errors:
        with transaction.atomic():
            locked_quote = Quote.objects.select_for_update().get(pk=quote.pk)
            existing_for_token = (
                QuoteItem.objects.filter(quote=locked_quote, creation_token=creation_token).first()
                if creation_token else None
            )
            if existing_for_token:
                item = existing_for_token
                created = False
            elif latest_article_version(code, revision) is not None:
                item = None
                created = False
            else:
                QuoteItem.objects.filter(quote=locked_quote).update(display_order=F("display_order") + 1)
                item = QuoteItem.objects.create(
                    quote=locked_quote,
                    code=code,
                    revision=revision,
                    creation_token=creation_token,
                    display_order=1,
                )
                initialize_item_phases(item)
                created = True
        if item is None:
            form.add_error("code", "La coppia codice e revisione è stata creata nel frattempo. Selezionala dalla ricerca e riprova.")
        elif created:
            return redirect("quotes:items", pk=pk)
        else:
            messages.info(request, f"Articolo {item.code} già aggiunto; il doppio invio è stato ignorato.")
            return redirect("quotes:items", pk=pk)

    if form.errors:
        messages.error(request, "Articolo non caricato: controllare codice e revisione.")
        return render_items(
            request, get_quote(request, pk), draft_load_form=form, status=422
        )
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.change_quoteitem", raise_exception=True)
@editable_quote_required
def item_edit(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    quote = get_quote(request, pk)
    item = get_object_or_404(QuoteItem, pk=item_id, quote=quote)
    prefix = f"item-{item.pk}" if request.method == "POST" else None
    form = QuoteItemForm(request.POST or None, instance=item, prefix=prefix)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Modifiche articolo salvate correttamente.")
        return redirect(f"{reverse('quotes:items', args=[pk])}?open_item={item.pk}")
    if request.method == "POST":
        messages.error(request, "Articolo non aggiornato: controllare i campi indicati.")
        return render_items(request, quote, item_form=form, status=422)
    return render(request, "quotes/item_edit.html", {"quote": quote, "item": item, "form": form, "step": 2})


@login_required
@permission_required("quotes.add_quoteitem", raise_exception=True)
@require_POST
@editable_quote_required
def item_duplicate(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    get_quote(request, pk)
    source = get_object_or_404(
        QuoteItem.objects.prefetch_related(
            "materials", "phases__operations", "phases__direct_costs", "phases__treatments"
        ),
        pk=item_id, quote_id=pk,
    )
    item = duplicate_item(source)
    messages.success(request, f"Articolo duplicato come {item.code}.")
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.delete_quoteitem", raise_exception=True)
@require_POST
@editable_quote_required
def item_delete(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    get_quote(request, pk)
    item = get_object_or_404(QuoteItem, pk=item_id, quote_id=pk)
    code = item.code
    item.delete()
    messages.success(request, f"Articolo {code} rimosso.")
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.add_itemmaterial", raise_exception=True)
@require_POST
@editable_quote_required
def material_add(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    get_quote(request, pk)
    item = get_object_or_404(QuoteItem, pk=item_id, quote_id=pk)
    form = ItemMaterialForm(request.POST, prefix=f"material-{item.pk}")
    if form.is_valid():
        material = form.cleaned_data["material"]
        if item.materials.filter(material=material).exists():
            form.add_error("material", "Questo materiale è già presente nell’articolo.")
        else:
            row = form.save(commit=False)
            row.item = item
            if row.unit_cost_snapshot is None:
                row.unit_cost_snapshot = material.current_cost_per_kg
            row.save()
            messages.success(request, "Materiale aggiunto con il costo corrente acquisito.")
            return redirect("quotes:items", pk=pk)
    messages.error(request, "Materiale non aggiunto: verificare materiale e peso.")
    return render_items(request, get_quote(request, pk), material_form=form, status=422)


@login_required
@permission_required("quotes.change_itemmaterial", raise_exception=True)
@require_POST
@editable_quote_required
def material_edit(request: HttpRequest, pk: int, material_id: int) -> HttpResponse:
    get_quote(request, pk)
    row = get_object_or_404(ItemMaterial, pk=material_id, item__quote_id=pk)
    form = ItemMaterialEditForm(request.POST, instance=row, prefix=f"material-edit-{row.pk}")
    if form.is_valid():
        form.save()
        messages.success(request, f"Costo e peso di {row.material.name} aggiornati solo per questo preventivo.")
    else:
        messages.error(request, "Materiale non aggiornato: controllare peso e costo di acquisto.")
    return redirect("quotes:items", pk=pk)


@login_required
@permission_required("quotes.delete_itemmaterial", raise_exception=True)
@require_POST
@editable_quote_required
def material_delete(request: HttpRequest, pk: int, material_id: int) -> HttpResponse:
    get_quote(request, pk)
    row = get_object_or_404(ItemMaterial, pk=material_id, item__quote_id=pk)
    row.delete()
    messages.success(request, "Materiale rimosso.")
    return redirect("quotes:items", pk=pk)


def build_phase_rows(quote: Quote):
    rows = []
    for item in quote.items.all():
        if item.phases.count() < len(phase_registry):
            initialize_item_phases(item)
            item._prefetched_objects_cache.pop("phases", None)
        phases = []
        for phase in item.phases.all():
            config = phase_registry[phase.definition.code]
            phase_form = PhaseForm(instance=phase, prefix=f"phase-{phase.pk}")
            phase_form.fields["active"].widget.attrs["form"] = f"phase-toggle-form-{phase.pk}"
            phase_form.fields["active"].widget.attrs["aria-label"] = f"Attiva {phase.definition.name}"
            operation_form = TimeOperationForm(phase=phase, prefix=f"op-{phase.pk}", initial={"operators_snapshot": 1})
            fixed_resource = operation_form.fields["resource"].queryset.first()
            if fixed_resource and operation_form.fields["resource"].queryset.count() == 1:
                operation_form.fields["operators_snapshot"].initial = fixed_resource.default_operators
            phases.append({
                "phase": phase, "config": config, "phase_form": phase_form,
                "operation_form": operation_form, "direct_form": DirectCostForm(prefix=f"cost-{phase.pk}", phase=phase),
                "treatment_form": TreatmentForm(prefix=f"treat-{phase.pk}"),
            })
        rows.append({
            "item": item,
            "phases": phases,
            "production_phases": [row for row in phases if row["config"].mode == "time"],
            "additional_phases": [row for row in phases if row["config"].mode != "time"],
        })
    return rows


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_work(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    record_workflow_step(quote, 3)
    return render(request, "quotes/work.html", {"quote": quote, "item_rows": build_phase_rows(quote), "step": 3})


@login_required
@permission_required("quotes.change_itemphase", raise_exception=True)
@require_POST
@editable_quote_required
def phase_update(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    get_quote(request, pk)
    phase = get_object_or_404(ItemPhase, pk=phase_id, item__quote_id=pk)
    form = PhaseForm(request.POST, instance=phase, prefix=f"phase-{phase.pk}")
    if form.is_valid():
        with transaction.atomic():
            phase = form.save()
            if phase.active and phase.definition.code == "acquisti-esterni":
                phase.internal_answer = ItemPhase.InternalAnswer.NO
                phase.save(update_fields=["internal_answer"])
            elif not phase.active:
                phase.operations.all().delete()
                phase.direct_costs.all().delete()
                phase.treatments.all().delete()
                phase.notes = ""
                phase.internal_answer = ItemPhase.InternalAnswer.TO_CHECK
                phase.save(update_fields=["notes", "internal_answer"])
    else:
        messages.error(request, "Fase non salvata: controllare i dati.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_timeoperation", raise_exception=True)
@require_POST
@editable_quote_required
def operation_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    get_quote(request, pk)
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
        messages.error(request, "Operazione non aggiunta. " + form_error_summary(form))
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.delete_timeoperation", raise_exception=True)
@require_POST
@editable_quote_required
def operation_delete(request: HttpRequest, pk: int, operation_id: int) -> HttpResponse:
    get_quote(request, pk)
    operation = get_object_or_404(TimeOperation, pk=operation_id, phase__item__quote_id=pk)
    operation.delete()
    messages.success(request, "Operazione rimossa.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_directcost", raise_exception=True)
@require_POST
@editable_quote_required
def direct_cost_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    get_quote(request, pk)
    phase = get_object_or_404(ItemPhase, pk=phase_id, item__quote_id=pk)
    if phase.definition.code not in {"lavorazioni-extra", "acquisti-esterni"}:
        messages.error(request, "Questa fase non accetta costi diretti.")
    else:
        form = DirectCostForm(request.POST, prefix=f"cost-{phase.pk}", phase=phase)
        if form.is_valid():
            row = form.save(commit=False)
            row.phase = phase
            row.save()
            phase.active = True
            if phase.definition.code == "acquisti-esterni":
                phase.internal_answer = ItemPhase.InternalAnswer.NO
                phase.save(update_fields=["active", "internal_answer"])
            else:
                phase.save(update_fields=["active"])
            messages.success(request, "Costo aggiunto.")
        else:
            messages.error(request, "Costo non aggiunto: controllare descrizione e importo.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.delete_directcost", raise_exception=True)
@require_POST
@editable_quote_required
def direct_cost_delete(request: HttpRequest, pk: int, cost_id: int) -> HttpResponse:
    get_quote(request, pk)
    get_object_or_404(DirectCost, pk=cost_id, phase__item__quote_id=pk).delete()
    messages.success(request, "Costo rimosso.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.add_externaltreatment", raise_exception=True)
@require_POST
@editable_quote_required
def treatment_add(request: HttpRequest, pk: int, phase_id: int) -> HttpResponse:
    get_quote(request, pk)
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
@editable_quote_required
def treatment_delete(request: HttpRequest, pk: int, treatment_id: int) -> HttpResponse:
    get_quote(request, pk)
    get_object_or_404(ExternalTreatment, pk=treatment_id, phase__item__quote_id=pk).delete()
    messages.success(request, "Trattamento rimosso.")
    return redirect("quotes:work", pk=pk)


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
@editable_quote_required
def quote_summary(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    if quote.items.exists():
        record_workflow_step(quote, 4)
    form = QuoteSummaryForm(request.POST or None, instance=quote)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Riepilogo economico e fattibilita salvati.")
        return redirect("quotes:summary", pk=pk)
    result = validate_quote(quote)
    summary_items = [
        {"item": item, "active_phases": list(item.phases.filter(active=True))}
        for item in quote.items.all()
    ]
    return render(request, "quotes/summary.html", {
        "quote": quote,
        "form": form,
        "validation": result,
        "summary_items": summary_items,
        "step": 4,
    })


@login_required
@permission_required("quotes.change_quote", raise_exception=True)
@require_POST
@editable_quote_required
def quote_complete(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
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
    duplicate = duplicate_quote(get_quote(request, pk), request.user)
    messages.success(request, f"Preventivo duplicato: {duplicate.number}.")
    return redirect("quotes:general", pk=duplicate.pk)


@login_required
@permission_required("quotes.archive_quote", raise_exception=True)
@require_POST
def quote_archive(request: HttpRequest, pk: int) -> HttpResponse:
    quote = get_quote(request, pk)
    archive_quotes(Quote.objects.filter(pk=quote.pk))
    messages.success(request, f"Preventivo {quote.number} archiviato. Nessun dato e stato cancellato.")
    return redirect("quotes:dashboard")


@login_required
@permission_required("quotes.archive_quote", raise_exception=True)
@require_POST
def quote_bulk_archive(request: HttpRequest) -> HttpResponse:
    scope = request.POST.get("scope", "selected")
    queryset = quote_queryset(request.user).exclude(status=Quote.Status.ARCHIVED)
    if scope == "selected":
        quote_ids = {
            int(value)
            for value in request.POST.getlist("quote_ids")
            if value.isdigit()
        }
        if not quote_ids:
            messages.warning(request, "Seleziona almeno un preventivo da archiviare.")
            return redirect("quotes:dashboard")
        queryset = queryset.filter(pk__in=quote_ids)
    elif scope != "all":
        messages.error(request, "Azione di archiviazione non valida.")
        return redirect("quotes:dashboard")

    archived_count = archive_quotes(queryset)
    if archived_count == 1:
        messages.success(request, "1 preventivo archiviato. Nessun dato è stato cancellato.")
    elif archived_count:
        messages.success(
            request,
            f"{archived_count} preventivi archiviati. Nessun dato è stato cancellato.",
        )
    else:
        messages.warning(request, "Nessun preventivo selezionato può essere archiviato.")
    return redirect("quotes:dashboard")


@login_required
@permission_required("quotes.archive_quote", raise_exception=True)
@require_POST
def quote_bulk_restore(request: HttpRequest) -> HttpResponse:
    query_string = request.META.get("QUERY_STRING", "")
    search_redirect = reverse("quotes:search")
    if query_string:
        search_redirect = f"{search_redirect}?{query_string}"
    scope = request.POST.get("scope", "selected")
    queryset = quote_queryset(request.user).filter(status=Quote.Status.ARCHIVED)
    if scope == "selected":
        quote_ids = {
            int(value)
            for value in request.POST.getlist("quote_ids")
            if value.isdigit()
        }
        if not quote_ids:
            messages.warning(request, "Seleziona almeno un preventivo da ripristinare.")
            return redirect(search_redirect)
        queryset = queryset.filter(pk__in=quote_ids)
    elif scope == "all":
        form = QuoteSearchForm(request.GET or None)
        if form.is_valid():
            queryset = apply_quote_filters(queryset, form.cleaned_data)
    else:
        messages.error(request, "Azione di ripristino non valida.")
        return redirect(search_redirect)

    restored_count = restore_quotes(queryset)
    if restored_count == 1:
        messages.success(request, "1 preventivo ripristinato nello stato precedente.")
    elif restored_count:
        messages.success(
            request,
            f"{restored_count} preventivi ripristinati nei rispettivi stati precedenti.",
        )
    else:
        messages.warning(request, "Nessun preventivo selezionato può essere ripristinato.")
    return redirect(search_redirect)


@login_required
@require_POST
def quote_delete(request: HttpRequest, pk: int) -> HttpResponse:
    if not request.user.is_superuser:
        raise PermissionDenied
    quote = get_quote(request, pk)
    number = quote.number
    quote.delete()
    messages.success(request, f"Preventivo {number} eliminato definitivamente.")
    return redirect("quotes:dashboard")


@login_required
@permission_required("quotes.view_quote", raise_exception=True)
def quote_search(request: HttpRequest) -> HttpResponse:
    form = QuoteSearchForm(request.GET or None)
    queryset = quote_queryset(request.user)
    if form.is_valid():
        queryset = apply_quote_filters(queryset, form.cleaned_data)
    has_archived_results = queryset.filter(status=Quote.Status.ARCHIVED).exists()
    queryset, sort, direction = sort_quotes(queryset, request, {
        "number": "number", "client": "client__name", "date": "date",
        "status": "status", "feasibility": "feasibility", "articles": "article_code",
    })
    page = Paginator(queryset, 50).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "quotes/search.html", {
        "form": form,
        "page": page,
        "filter_query": query_params.urlencode(),
        "has_archived_results": has_archived_results,
        "sort": sort,
        "direction": direction,
    })

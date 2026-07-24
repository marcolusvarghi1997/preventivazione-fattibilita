from django.db import transaction
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from apps.catalog.models import PhaseDefinition
from apps.quotes.models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


def initialize_item_phases(item: QuoteItem) -> None:
    for definition in PhaseDefinition.objects.filter(active=True).order_by("display_order"):
        ItemPhase.objects.get_or_create(
            item=item, definition=definition,
            defaults={"display_order": definition.display_order},
        )


class ArticleVersionConflict(ValueError):
    """La versione scelta non coincide più con l'ultima disponibile."""


def latest_article_version(code: str, revision: str):
    return (
        QuoteItem.objects.filter(code=code.strip(), revision=revision.strip())
        .order_by("-article_date", "-pk")
        .first()
    )


def search_latest_article_versions(*, code: str = ""):
    """Restituisce una sola versione, la più recente, per ogni coppia codice/revisione."""
    latest_pk_for_key = (
        QuoteItem.objects.filter(
            code=OuterRef("code"),
            revision=OuterRef("revision"),
        )
        .order_by("-article_date", "-pk")
        .values("pk")[:1]
    )
    queryset = QuoteItem.objects.annotate(
        latest_key_pk=Subquery(latest_pk_for_key)
    ).filter(pk=F("latest_key_pk"))
    if code.strip():
        queryset = queryset.filter(code__icontains=code.strip())
    return queryset.select_related("quote").order_by("code", "revision")


@transaction.atomic
def archive_quotes(queryset) -> int:
    quote_ids = list(
        queryset.exclude(status=Quote.Status.ARCHIVED).values_list("pk", flat=True)
    )
    quotes = list(Quote.objects.select_for_update().filter(pk__in=quote_ids))
    if not quotes:
        return 0
    now = timezone.now()
    for quote in quotes:
        quote.status_before_archive = quote.status
        quote.status = Quote.Status.ARCHIVED
        quote.updated_at = now
    Quote.objects.bulk_update(
        quotes,
        ("status", "status_before_archive", "updated_at"),
    )
    return len(quotes)


@transaction.atomic
def restore_quotes(queryset) -> int:
    quote_ids = list(
        queryset.filter(status=Quote.Status.ARCHIVED).values_list("pk", flat=True)
    )
    quotes = list(Quote.objects.select_for_update().filter(pk__in=quote_ids))
    if not quotes:
        return 0
    restorable_statuses = set(Quote.Status.values) - {Quote.Status.ARCHIVED}
    now = timezone.now()
    for quote in quotes:
        quote.status = (
            quote.status_before_archive
            if quote.status_before_archive in restorable_statuses
            else Quote.Status.DRAFT
        )
        quote.status_before_archive = ""
        quote.updated_at = now
    Quote.objects.bulk_update(
        quotes,
        ("status", "status_before_archive", "updated_at"),
    )
    return len(quotes)


def _copy_item(
    source: QuoteItem,
    quote: Quote,
    *,
    code: str | None = None,
    revision: str | None = None,
    display_order: int | None = None,
    creation_token=None,
    source_version: QuoteItem | None = None,
) -> QuoteItem:
    item = QuoteItem.objects.create(
        quote=quote,
        source_version=source_version,
        creation_token=creation_token,
        code=source.code if code is None else code,
        quantity=source.quantity,
        description=source.description,
        revision=source.revision if revision is None else revision,
        legacy_dimensions=source.legacy_dimensions,
        length_mm=source.length_mm, height_mm=source.height_mm, depth_mm=source.depth_mm,
        technical_notes=source.technical_notes,
        feasibility=source.feasibility,
        external_purchases=source.external_purchases,
        external_purchases_cost=source.external_purchases_cost,
        external_work=source.external_work,
        external_work_cost=source.external_work_cost,
        bureaucracy=source.bureaucracy,
        bureaucracy_cost=source.bureaucracy_cost,
        feasibility_manually_set=source.feasibility_manually_set,
        display_order=display_order or source.display_order,
    )
    ItemMaterial.objects.bulk_create([
        ItemMaterial(item=item, material=row.material, weight_kg=row.weight_kg, unit_cost_snapshot=row.unit_cost_snapshot)
        for row in source.materials.all()
    ])
    for old_phase in source.phases.all():
        phase = ItemPhase.objects.create(
            item=item, definition=old_phase.definition, active=old_phase.active,
            notes=old_phase.notes, display_order=old_phase.display_order,
            internal_answer=old_phase.internal_answer,
        )
        TimeOperation.objects.bulk_create([
            TimeOperation(
                phase=phase, resource=op.resource, working_minutes=op.working_minutes,
                setup_minutes=op.setup_minutes, operators_snapshot=op.operators_snapshot,
                time_basis=op.time_basis, resource_name_snapshot=op.resource_name_snapshot,
                hourly_cost_snapshot=op.hourly_cost_snapshot, notes=op.notes,
            ) for op in old_phase.operations.all()
        ])
        DirectCost.objects.bulk_create([
            DirectCost(phase=phase, description=row.description, supplier=row.supplier, amount=row.amount, notes=row.notes)
            for row in old_phase.direct_costs.all()
        ])
        ExternalTreatment.objects.bulk_create([
            ExternalTreatment(
                phase=phase, treatment_type=row.treatment_type, description=row.description,
                supplier=row.supplier, cost=row.cost, notes=row.notes,
            ) for row in old_phase.treatments.all()
        ])
    return item


@transaction.atomic
def create_article_version_from_latest(
    *,
    code: str,
    quote: Quote,
    revision: str,
    creation_token=None,
    expected_source_id: int | None = None,
) -> tuple[QuoteItem, bool]:
    """Clona in profondità l'ultima versione del codice nel preventivo indicato."""
    code = code.strip()
    Quote.objects.select_for_update().get(pk=quote.pk)
    if creation_token:
        existing = QuoteItem.objects.filter(quote=quote, creation_token=creation_token).first()
        if existing:
            return existing, False
    revision = revision.strip()
    if QuoteItem.objects.filter(quote=quote, code=code, revision=revision).exists():
        raise ArticleVersionConflict("Questa coppia codice e revisione è già stata aggiunta al preventivo.")
    if expected_source_id is not None:
        selected = QuoteItem.objects.filter(pk=expected_source_id, code=code).first()
        if selected is None or selected.revision != revision:
            raise ArticleVersionConflict("L’articolo selezionato non corrisponde a codice e revisione indicati.")
        latest = latest_article_version(code, selected.revision)
        if latest is None or latest.pk != selected.pk:
            raise ArticleVersionConflict(
                "Nel frattempo l’articolo è stato aggiornato. Ripeti la ricerca e carica nuovamente il risultato."
            )
    else:
        latest = latest_article_version(code, revision)
        if latest is None:
            raise ArticleVersionConflict("L’articolo selezionato non è più disponibile.")
    QuoteItem.objects.filter(quote=quote).update(display_order=F("display_order") + 1)
    item = _copy_item(
        latest,
        quote,
        revision=revision,
        display_order=1,
        creation_token=creation_token,
        source_version=latest,
    )
    return item, True


@transaction.atomic
def duplicate_item(source: QuoteItem) -> QuoteItem:
    suffix = "-COPIA"
    code = f"{source.code[:100 - len(suffix)]}{suffix}"
    return _copy_item(
        source,
        source.quote,
        code=code,
        display_order=source.quote.items.count() + 1,
        source_version=source,
    )


@transaction.atomic
def duplicate_quote(source: Quote, author) -> Quote:
    duplicate = Quote.objects.create(
        client=source.client,
        client_contact=source.client_contact,
        client_email=source.client_email,
        internal_notes=source.internal_notes,
        customer_notes=source.customer_notes,
        feasibility=source.feasibility,
        offered_price=source.offered_price,
        customer_decision=Quote.CustomerDecision.PENDING,
        author=author,
        status=Quote.Status.DRAFT,
    )
    for source_item in source.items.prefetch_related(
        "materials", "phases__operations", "phases__direct_costs", "phases__treatments"
    ):
        _copy_item(source_item, duplicate, source_version=source_item)
    return duplicate

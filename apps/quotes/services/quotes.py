from django.db import transaction
from apps.catalog.models import PhaseDefinition
from apps.quotes.models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


def initialize_item_phases(item: QuoteItem) -> None:
    for definition in PhaseDefinition.objects.filter(active=True).order_by("display_order"):
        ItemPhase.objects.get_or_create(
            item=item, definition=definition,
            defaults={"display_order": definition.display_order},
        )


def _copy_item(source: QuoteItem, quote: Quote, *, code: str | None = None, display_order: int | None = None) -> QuoteItem:
    item = QuoteItem.objects.create(
        quote=quote, code=code or source.code, quantity=source.quantity,
        description=source.description, revision=source.revision,
        dimensions=source.dimensions, technical_notes=source.technical_notes,
        feasibility=source.feasibility,
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
def duplicate_item(source: QuoteItem) -> QuoteItem:
    suffix = "-COPIA"
    code = f"{source.code[:100 - len(suffix)]}{suffix}"
    return _copy_item(source, source.quote, code=code, display_order=source.quote.items.count() + 1)


@transaction.atomic
def duplicate_quote(source: Quote, author) -> Quote:
    duplicate = Quote.objects.create(
        client=source.client,
        client_contact=source.client_contact,
        internal_notes=source.internal_notes,
        customer_notes=source.customer_notes,
        feasibility=source.feasibility,
        offered_price=source.offered_price,
        author=author,
        status=Quote.Status.DRAFT,
    )
    for source_item in source.items.prefetch_related(
        "materials", "phases__operations", "phases__direct_costs", "phases__treatments"
    ):
        _copy_item(source_item, duplicate)
    return duplicate

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.catalog.models import Client, Material, PhaseDefinition, ProductionResource
from apps.quotes.models import ItemMaterial, Quote, QuoteItem, TimeOperation
from apps.quotes.services.quotes import initialize_item_phases


PASSWORD = "Playwright-2026!"


def add_item(quote, material, code, order):
    item = QuoteItem.objects.create(
        quote=quote,
        code=code,
        quantity=2,
        description=f"Articolo automatico {code}",
        display_order=order,
    )
    ItemMaterial.objects.create(
        item=item,
        material=material,
        weight_kg=Decimal("1.500"),
        unit_cost_snapshot=material.current_cost_per_kg,
    )
    initialize_item_phases(item)
    return item


def add_operation(item, phase_code, hourly_cost):
    definition = PhaseDefinition.objects.get(code=phase_code)
    phase = item.phases.get(definition=definition)
    phase.active = True
    phase.save(update_fields=["active"])
    resource = ProductionResource.objects.filter(phase=definition).first()
    return TimeOperation.objects.create(
        phase=phase,
        resource=resource,
        working_minutes=Decimal("20"),
        setup_minutes=Decimal("5"),
        operators_snapshot=1,
        resource_name_snapshot=resource.name,
        hourly_cost_snapshot=Decimal(hourly_cost),
    )


def main(output_path):
    user = get_user_model().objects.create_user("playwright", password=PASSWORD)
    user.groups.add(Group.objects.get(name="Commerciale"))
    client = Client.objects.create(name="Cliente Playwright")
    material = Material.objects.create(
        name="Acciaio Playwright",
        current_cost_per_kg=Decimal("2.5000"),
    )

    main_quote = Quote.objects.create(author=user, client=client, offered_price=Decimal("500"))
    main_item = add_item(main_quote, material, "PW-01", 1)
    add_item(main_quote, material, "PW-02", 2)
    main_operation = add_operation(main_item, "saldatura", "45")

    archived_quote = Quote.objects.create(
        author=user,
        client=client,
        offered_price=Decimal("100"),
        status=Quote.Status.ARCHIVED,
    )
    add_item(archived_quote, material, "ARCH-01", 1)

    zero_cost_quote = Quote.objects.create(author=user, client=client, offered_price=Decimal("200"))
    zero_cost_item = add_item(zero_cost_quote, material, "ZERO-01", 1)
    add_operation(zero_cost_item, "sabbiatura", "0")

    data = {
        "username": user.username,
        "password": PASSWORD,
        "main_quote": main_quote.pk,
        "main_operation": main_operation.pk,
        "archived_quote": archived_quote.pk,
        "zero_cost_quote": zero_cost_quote.pk,
    }
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump(data, output)


if __name__ == "__main__":
    main(sys.argv[1])

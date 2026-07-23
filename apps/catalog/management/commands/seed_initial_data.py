from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import PhaseDefinition, ProductionResource
from apps.quotes.phases import phase_registry

RESOURCE_TYPES = ProductionResource.ResourceType

RESOURCES = {
    "taglio-lamiera": [("Combinata ACIES", RESOURCE_TYPES.MACHINE, True), ("Laser 9kW", RESOURCE_TYPES.MACHINE, True)],
    "taglio-profili": [("Taglio Profili", RESOURCE_TYPES.FIXED, False)],
    "piegatura": [(name, RESOURCE_TYPES.MACHINE, True) for name in ("HG1003ATC", "HG2204ATC", "HD1003", "SAFAN")],
    "macchine-utensili": [(name, RESOURCE_TYPES.MACHINE, True) for name in ("FAGIMA", "VF3", "MINIMILL", "MORI SEIKI", "TORNIO HAAS")],
    "saldatura": [("Saldatura Manuale", RESOURCE_TYPES.MANUAL, True), ("Saldatura Robot", RESOURCE_TYPES.MACHINE, True)],
    "sabbiatura": [("Sabbiatura", RESOURCE_TYPES.FIXED, False)],
    "molatura": [("Molatura", RESOURCE_TYPES.MANUAL, False)],
    "assemblaggio": [("Assemblaggio", RESOURCE_TYPES.MANUAL, False)],
}


class Command(BaseCommand):
    help = "Crea o aggiorna fasi, risorse e gruppi applicativi iniziali."

    @transaction.atomic
    def handle(self, *args, **options):
        phases = {}
        for config in phase_registry.values():
            phases[config.code], _ = PhaseDefinition.objects.update_or_create(
                code=config.code,
                defaults={"name": config.name, "display_order": config.order, "active": True},
            )
        for code, resources in RESOURCES.items():
            for name, resource_type, selectable in resources:
                ProductionResource.objects.update_or_create(
                    phase=phases[code], name=name,
                    defaults={
                        "resource_type": resource_type,
                        "user_selectable": selectable,
                        "active": True,
                        "default_operators": 1,
                    },
                )

        commercial, _ = Group.objects.get_or_create(name="Commerciale")
        commercial_codenames = {
            "view_quote", "add_quote", "change_quote", "duplicate_quote", "archive_quote", "generate_quote_pdf",
            "view_quoteitem", "add_quoteitem", "change_quoteitem", "delete_quoteitem",
            "view_itemmaterial", "add_itemmaterial", "change_itemmaterial", "delete_itemmaterial",
            "view_itemphase", "change_itemphase", "view_timeoperation", "add_timeoperation", "change_timeoperation", "delete_timeoperation",
            "view_directcost", "add_directcost", "change_directcost", "delete_directcost",
            "view_externaltreatment", "add_externaltreatment", "change_externaltreatment", "delete_externaltreatment",
            "view_client", "add_client", "view_clientcontact", "add_clientcontact",
            "view_material", "view_productionresource", "view_phasedefinition",
        }
        commercial.permissions.set(Permission.objects.filter(codename__in=commercial_codenames))

        administrators, _ = Group.objects.get_or_create(name="Amministratore")
        administrators.permissions.set(Permission.objects.filter(content_type__app_label__in=["catalog", "quotes", "auth"]))
        self.stdout.write(self.style.SUCCESS("Dati iniziali e gruppi aggiornati correttamente."))

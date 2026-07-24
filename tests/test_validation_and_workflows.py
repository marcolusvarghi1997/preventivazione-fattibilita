from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Material, PhaseDefinition, ProductionResource
from apps.quotes.forms import TreatmentForm
from apps.quotes.models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from apps.quotes.services.quotes import duplicate_item, duplicate_quote
from apps.quotes.services.validation import validate_quote


class ValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("validator", password="pass")
        cls.material = Material.objects.create(name="Test material", current_cost_per_kg=Decimal("1"))

    def setUp(self):
        self.quote = Quote.objects.create(author=self.user)
        self.item = QuoteItem.objects.create(quote=self.quote, code="TEST", quantity=1)
        ItemMaterial.objects.create(item=self.item, material=self.material, weight_kg=Decimal("1"), unit_cost_snapshot=Decimal("1"))

    def test_external_purchase_required_when_not_internal(self):
        phase = ItemPhase.objects.create(
            item=self.item, definition=PhaseDefinition.objects.get(code="acquisti-esterni"),
            active=True, internal_answer=ItemPhase.InternalAnswer.NO, display_order=10,
        )
        result = validate_quote(self.quote)
        self.assertTrue(any("costo esterno" in error.lower() for error in result.errors))
        DirectCost.objects.create(phase=phase, description="Acquisto", amount=Decimal("10"))
        result = validate_quote(self.quote)
        self.assertFalse(any("costo esterno" in error.lower() for error in result.errors))

    def test_other_treatment_requires_description(self):
        form = TreatmentForm(data={"treatment_type": ExternalTreatment.TreatmentType.OTHER, "description": "", "supplier": "", "cost": "12", "notes": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_zero_resource_cost_blocks_completion(self):
        phase_def = PhaseDefinition.objects.get(code="sabbiatura")
        phase = ItemPhase.objects.create(item=self.item, definition=phase_def, active=True, display_order=6)
        resource = ProductionResource.objects.get(phase=phase_def)
        TimeOperation.objects.create(
            phase=phase, resource=resource, working_minutes=Decimal("10"), setup_minutes=0,
            operators_snapshot=1, resource_name_snapshot=resource.name, hourly_cost_snapshot=0,
        )
        result = validate_quote(self.quote)
        self.assertFalse(result.can_complete)
        self.assertTrue(any("costo orario" in error.lower() for error in result.errors))
        self.assertFalse(any("costo orario" in warning.lower() for warning in result.warnings))


class HighSeverityWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("workflow", password="pass")
        cls.user.groups.add(Group.objects.get(name="Commerciale"))
        cls.material = Material.objects.create(name="Workflow material", current_cost_per_kg=Decimal("2"))

    def setUp(self):
        self.quote = Quote.objects.create(author=self.user, offered_price=Decimal("100"))
        self.item = QuoteItem.objects.create(quote=self.quote, code="FLOW", quantity=1)
        ItemMaterial.objects.create(
            item=self.item,
            material=self.material,
            weight_kg=Decimal("1"),
            unit_cost_snapshot=Decimal("2"),
        )
        self.client.force_login(self.user)

    def test_archived_quote_rejects_summary_and_nested_writes(self):
        self.quote.status = Quote.Status.ARCHIVED
        self.quote.save(update_fields=["status"])

        summary_response = self.client.post(
            reverse("quotes:summary", args=[self.quote.pk]),
            {"feasibility": "internal", "offered_price": "999"},
            follow=True,
        )
        delete_response = self.client.post(
            reverse("quotes:item_delete", args=[self.quote.pk, self.item.pk]),
            follow=True,
        )

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.offered_price, Decimal("100"))
        self.assertTrue(QuoteItem.objects.filter(pk=self.item.pk).exists())
        self.assertContains(summary_response, "non puo essere modificato")
        self.assertContains(delete_response, "non puo essere modificato")

    def test_operation_error_message_includes_invalid_field(self):
        phase_def = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(item=self.item, definition=phase_def, active=True, display_order=5)
        resource = ProductionResource.objects.filter(phase=phase_def).first()

        response = self.client.post(reverse("quotes:operation_add", args=[self.quote.pk, phase.pk]), {
            f"op-{phase.pk}-resource": resource.pk,
            f"op-{phase.pk}-working_minutes": "10",
            f"op-{phase.pk}-setup_minutes": "0",
            f"op-{phase.pk}-operators_snapshot": "0",
            f"op-{phase.pk}-time_basis": "per_piece",
            f"op-{phase.pk}-notes": "",
        }, follow=True)

        self.assertContains(response, "Operatori")
        self.assertContains(response, "maggiore o uguale a 1")
        self.assertFalse(phase.operations.exists())

    def test_deactivating_phase_clears_all_saved_phase_data_without_success_banner(self):
        phase_def = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(
            item=self.item,
            definition=phase_def,
            active=True,
            display_order=5,
            notes="Nota fase",
            internal_answer=ItemPhase.InternalAnswer.YES,
        )
        resource = ProductionResource.objects.filter(phase=phase_def).first()
        TimeOperation.objects.create(
            phase=phase,
            resource=resource,
            working_minutes=Decimal("10"),
            setup_minutes=Decimal("2"),
            operators_snapshot=1,
            resource_name_snapshot=resource.name,
            hourly_cost_snapshot=resource.hourly_cost_per_person,
        )
        DirectCost.objects.create(phase=phase, description="Costo salvato", amount=Decimal("15"))
        ExternalTreatment.objects.create(
            phase=phase,
            treatment_type=ExternalTreatment.TreatmentType.PAINTING,
            cost=Decimal("20"),
        )

        response = self.client.post(
            reverse("quotes:phase_update", args=[self.quote.pk, phase.pk]),
            {},
            follow=True,
        )

        phase.refresh_from_db()
        self.assertFalse(phase.active)
        self.assertEqual(phase.notes, "")
        self.assertEqual(phase.internal_answer, ItemPhase.InternalAnswer.TO_CHECK)
        self.assertFalse(phase.operations.exists())
        self.assertFalse(phase.direct_costs.exists())
        self.assertFalse(phase.treatments.exists())
        self.assertNotContains(response, "aggiornata automaticamente")


class DuplicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.author = get_user_model().objects.create_user("author", password="pass")
        cls.other_author = get_user_model().objects.create_user("copy", password="pass")
        cls.material = Material.objects.create(name="Dup material", current_cost_per_kg=Decimal("2"))

    def test_duplicate_quote_copies_nested_data_and_snapshots(self):
        source = Quote.objects.create(author=self.author, internal_notes="Interna", offered_price=Decimal("500"), status=Quote.Status.SENT)
        item = QuoteItem.objects.create(quote=source, code="DUP", quantity=3)
        ItemMaterial.objects.create(item=item, material=self.material, weight_kg=Decimal("2"), unit_cost_snapshot=Decimal("2"))
        phase_def = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(item=item, definition=phase_def, active=True, display_order=5)
        resource = ProductionResource.objects.filter(phase=phase_def).first()
        TimeOperation.objects.create(
            phase=phase, resource=resource, working_minutes=Decimal("15"), setup_minutes=Decimal("5"),
            operators_snapshot=2, resource_name_snapshot="Nome storico", hourly_cost_snapshot=Decimal("44"), notes="nota",
        )
        duplicate = duplicate_quote(source, self.other_author)
        self.assertNotEqual(duplicate.number, source.number)
        self.assertEqual(duplicate.status, Quote.Status.DRAFT)
        self.assertEqual(duplicate.author, self.other_author)
        copied_op = duplicate.items.get().phases.get().operations.get()
        self.assertEqual(copied_op.hourly_cost_snapshot, Decimal("44"))
        self.assertEqual(copied_op.resource_name_snapshot, "Nome storico")
        self.assertEqual(duplicate.items.get().materials.get().unit_cost_snapshot, Decimal("2"))

    def test_duplicate_item_keeps_material_and_operation_snapshots(self):
        quote = Quote.objects.create(author=self.author)
        item = QuoteItem.objects.create(quote=quote, code="PEZZO", quantity=2)
        ItemMaterial.objects.create(item=item, material=self.material, weight_kg=Decimal("1.5"), unit_cost_snapshot=Decimal("2"))
        phase_def = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(item=item, definition=phase_def, active=True)
        resource = ProductionResource.objects.filter(phase=phase_def).first()
        TimeOperation.objects.create(
            phase=phase, resource=resource, working_minutes=Decimal("10"), setup_minutes=Decimal("2"),
            operators_snapshot=1, resource_name_snapshot="Risorsa storica", hourly_cost_snapshot=Decimal("37"),
        )

        copied = duplicate_item(item)

        self.assertEqual(copied.code, "PEZZO-COPIA")
        self.assertEqual(copied.materials.get().unit_cost_snapshot, Decimal("2"))
        copied_operation = copied.phases.get().operations.get()
        self.assertEqual(copied_operation.resource_name_snapshot, "Risorsa storica")
        self.assertEqual(copied_operation.hourly_cost_snapshot, Decimal("37"))

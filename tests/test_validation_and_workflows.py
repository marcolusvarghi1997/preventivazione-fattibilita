from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import Material, PhaseDefinition, ProductionResource
from apps.quotes.forms import TreatmentForm
from apps.quotes.models import DirectCost, ExternalTreatment, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from apps.quotes.services.quotes import duplicate_quote
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

    def test_zero_resource_cost_is_warning_not_error(self):
        phase_def = PhaseDefinition.objects.get(code="sabbiatura")
        phase = ItemPhase.objects.create(item=self.item, definition=phase_def, active=True, display_order=6)
        resource = ProductionResource.objects.get(phase=phase_def)
        TimeOperation.objects.create(
            phase=phase, resource=resource, working_minutes=Decimal("10"), setup_minutes=0,
            operators_snapshot=1, resource_name_snapshot=resource.name, hourly_cost_snapshot=0,
        )
        result = validate_quote(self.quote)
        self.assertFalse(result.errors)
        self.assertTrue(any("costo orario" in warning.lower() for warning in result.warnings))


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

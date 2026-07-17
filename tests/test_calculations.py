from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.management import call_command

from apps.catalog.models import Material, PhaseDefinition, ProductionResource
from apps.quotes.models import ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from apps.quotes.services.calculations import calculate_time_cost


class CalculationServiceTests(TestCase):
    def test_cost_per_piece(self):
        result = calculate_time_cost(working_minutes=Decimal("30"), setup_minutes=Decimal("0"), hourly_cost=Decimal("40"), operators=1, quantity=10, per_piece=True)
        self.assertEqual(result, Decimal("200"))

    def test_cost_per_lot(self):
        result = calculate_time_cost(working_minutes=Decimal("30"), setup_minutes=Decimal("0"), hourly_cost=Decimal("40"), operators=1, quantity=10, per_piece=False)
        self.assertEqual(result, Decimal("20"))

    def test_setup_is_not_multiplied_by_quantity(self):
        result = calculate_time_cost(working_minutes=Decimal("0"), setup_minutes=Decimal("30"), hourly_cost=Decimal("40"), operators=1, quantity=100, per_piece=True)
        self.assertEqual(result, Decimal("20"))

    def test_multiple_operators(self):
        result = calculate_time_cost(working_minutes=Decimal("60"), setup_minutes=Decimal("0"), hourly_cost=Decimal("35"), operators=3, quantity=1, per_piece=False)
        self.assertEqual(result, Decimal("105"))


class ModelTotalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("totals", password="pass")
        cls.material1 = Material.objects.create(name="S235", current_cost_per_kg=Decimal("2.50"))
        cls.material2 = Material.objects.create(name="Inox", current_cost_per_kg=Decimal("5.00"))

    def setUp(self):
        self.quote = Quote.objects.create(author=self.user)
        self.item = QuoteItem.objects.create(quote=self.quote, code="A-01", quantity=2)
        self.phase_def = PhaseDefinition.objects.get(code="saldatura")
        self.phase = ItemPhase.objects.create(item=self.item, definition=self.phase_def, active=True, display_order=5)

    def add_operation(self, resource, minutes="60", setup="0", hourly=None):
        return TimeOperation.objects.create(
            phase=self.phase, resource=resource, working_minutes=Decimal(minutes), setup_minutes=Decimal(setup),
            operators_snapshot=1, time_basis=TimeOperation.TimeBasis.LOT,
            resource_name_snapshot=resource.name, hourly_cost_snapshot=hourly if hourly is not None else resource.hourly_cost_per_person,
        )

    def test_multiple_operations_in_same_phase(self):
        resources = list(ProductionResource.objects.filter(phase=self.phase_def))
        self.add_operation(resources[0], hourly=Decimal("30"))
        self.add_operation(resources[1], minutes="30", hourly=Decimal("40"))
        self.assertEqual(self.phase.total_cost, Decimal("50"))

    def test_multiple_materials_and_item_total(self):
        ItemMaterial.objects.create(item=self.item, material=self.material1, weight_kg=Decimal("10"), unit_cost_snapshot=Decimal("2.50"))
        ItemMaterial.objects.create(item=self.item, material=self.material2, weight_kg=Decimal("1"), unit_cost_snapshot=Decimal("5"))
        resource = ProductionResource.objects.filter(phase=self.phase_def).first()
        self.add_operation(resource, hourly=Decimal("30"))
        self.assertEqual(self.item.material_cost, Decimal("60"))
        self.assertEqual(self.item.total_cost, Decimal("90"))

    def test_missing_material_cost_does_not_block_total(self):
        row = ItemMaterial.objects.create(item=self.item, material=self.material1, weight_kg=Decimal("10"), unit_cost_snapshot=None)
        self.assertIsNone(row.total_cost)
        self.assertTrue(self.item.has_missing_material_cost)
        self.assertEqual(self.item.material_cost, Decimal("0"))

    def test_resource_cost_snapshot_is_historical(self):
        resource = ProductionResource.objects.filter(phase=self.phase_def).first()
        resource.hourly_cost_per_person = Decimal("30")
        resource.save()
        operation = self.add_operation(resource)
        self.assertEqual(operation.total_cost, Decimal("30"))
        resource.hourly_cost_per_person = Decimal("99")
        resource.save()
        operation.refresh_from_db()
        self.assertEqual(operation.hourly_cost_snapshot, Decimal("30"))
        self.assertEqual(operation.total_cost, Decimal("30"))

    def test_quote_total_sums_items(self):
        ItemMaterial.objects.create(item=self.item, material=self.material1, weight_kg=Decimal("2"), unit_cost_snapshot=Decimal("2.50"))
        other = QuoteItem.objects.create(quote=self.quote, code="B-02", quantity=1)
        ItemMaterial.objects.create(item=other, material=self.material2, weight_kg=Decimal("3"), unit_cost_snapshot=Decimal("5"))
        self.assertEqual(self.quote.industrial_cost, Decimal("25"))

    def test_inactive_phase_cost_is_zero(self):
        resource = ProductionResource.objects.filter(phase=self.phase_def).first()
        self.add_operation(resource, hourly=Decimal("100"))
        self.phase.active = False
        self.phase.save()
        self.assertEqual(self.phase.total_cost, Decimal("0"))

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalog.models import Client, ClientContact, Material, PhaseDefinition, ProductionResource, SiteConfiguration
from apps.quotes.formatting import format_decimal_it, format_money, format_weight, normalize_decimal_input
from apps.quotes.forms import ItemMaterialEditForm, QuoteItemForm, QuoteSummaryForm
from apps.quotes.models import ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation


class RequestedPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        group = Group.objects.get(name="Commerciale")
        cls.owner = get_user_model().objects.create_user("owner", password="pass")
        cls.other = get_user_model().objects.create_user("other", password="pass")
        cls.owner.groups.add(group)
        cls.other.groups.add(group)
        cls.owner_quote = Quote.objects.create(author=cls.owner)
        cls.other_quote = Quote.objects.create(author=cls.other)

    def test_user_sees_and_opens_only_own_quotes(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("quotes:dashboard"))
        self.assertContains(response, self.owner_quote.number)
        self.assertNotContains(response, self.other_quote.number)
        self.assertEqual(self.client.get(reverse("quotes:summary", args=[self.other_quote.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("quotes:pdf", args=[self.other_quote.pk])).status_code, 404)

    def test_regular_user_cannot_delete_quote(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("quotes:delete", args=[self.owner_quote.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Quote.objects.filter(pk=self.owner_quote.pk).exists())

    def test_superuser_can_delete_quote(self):
        superuser = get_user_model().objects.create_superuser("root", password="pass")
        self.client.force_login(superuser)
        response = self.client.post(reverse("quotes:delete", args=[self.other_quote.pk]))
        self.assertRedirects(response, reverse("quotes:dashboard"))
        self.assertFalse(Quote.objects.filter(pk=self.other_quote.pk).exists())

    def test_preventivi_root_points_to_dashboard(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/preventivi/").status_code, 200)


class RequestedEconomicRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("costs", password="pass")
        cls.user.groups.add(Group.objects.get(name="Commerciale"))
        cls.material = Material.objects.create(name="Acciaio test", current_cost_per_kg=Decimal("2.5000"))

    def setUp(self):
        self.quote = Quote.objects.create(author=self.user, offered_price=Decimal("150.00"))
        self.item = QuoteItem.objects.create(
            quote=self.quote,
            code="EXT-01",
            quantity=2,
            external_purchases=True,
            external_purchases_cost=Decimal("10.00"),
            external_work=True,
            external_work_cost=Decimal("20.00"),
            bureaucracy=True,
            bureaucracy_cost=Decimal("5.00"),
        )
        self.row = ItemMaterial.objects.create(
            item=self.item,
            material=self.material,
            weight_kg=Decimal("3.000"),
            unit_cost_snapshot=Decimal("2.5000"),
        )
        self.client.force_login(self.user)

    def test_optional_article_costs_are_added_with_decimal(self):
        self.assertEqual(self.item.supplementary_cost, Decimal("35.00"))
        self.assertEqual(self.item.total_cost, Decimal("50.0000"))
        self.assertEqual(self.quote.profit_percent, Decimal("200"))

    def test_material_snapshot_is_editable_without_changing_catalog(self):
        response = self.client.post(reverse("quotes:material_edit", args=[self.quote.pk, self.row.pk]), {
            f"material-edit-{self.row.pk}-weight_kg": "4.000",
            f"material-edit-{self.row.pk}-unit_cost_snapshot": "3.7500",
        })
        self.assertRedirects(response, reverse("quotes:items", args=[self.quote.pk]))
        self.row.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(self.row.unit_cost_snapshot, Decimal("3.7500"))
        self.assertEqual(self.material.current_cost_per_kg, Decimal("2.5000"))

    def test_decimal_fields_accept_comma_and_dot_without_float(self):
        material_form = ItemMaterialEditForm(data={"weight_kg": "4,125", "unit_cost_snapshot": "3.75"})
        summary_form = QuoteSummaryForm(data={
            "feasibility": "to_check",
            "offered_price": "1234,56",
            "customer_decision": "pending",
        }, instance=self.quote)
        self.assertTrue(material_form.is_valid(), material_form.errors)
        self.assertTrue(summary_form.is_valid(), summary_form.errors)
        self.assertEqual(material_form.cleaned_data["weight_kg"], Decimal("4.125"))
        self.assertEqual(material_form.cleaned_data["unit_cost_snapshot"], Decimal("3.75"))
        self.assertEqual(summary_form.cleaned_data["offered_price"], Decimal("1234.56"))

    def test_disabled_supplementary_cost_is_preserved_but_not_calculated(self):
        form = QuoteItemForm(data={
            "code": self.item.code,
            "quantity": self.item.quantity,
            "description": self.item.description,
            "revision": self.item.revision,
            "dimensions": self.item.dimensions,
            "technical_notes": self.item.technical_notes,
            "feasibility": self.item.feasibility,
        }, instance=self.item)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.external_purchases_cost, Decimal("10.00"))
        self.assertEqual(self.item.external_work_cost, Decimal("20.00"))
        self.assertEqual(self.item.bureaucracy_cost, Decimal("5.00"))
        self.assertEqual(self.item.supplementary_cost, Decimal("0"))

    def test_operation_endpoint_accepts_comma_and_persists_decimal(self):
        definition = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(item=self.item, definition=definition, active=True, display_order=5)
        resource = ProductionResource.objects.filter(phase=definition).first()
        response = self.client.post(reverse("quotes:operation_add", args=[self.quote.pk, phase.pk]), {
            f"op-{phase.pk}-resource": resource.pk,
            f"op-{phase.pk}-working_minutes": "10,50",
            f"op-{phase.pk}-setup_minutes": "1.25",
            f"op-{phase.pk}-operators_snapshot": "1",
            f"op-{phase.pk}-time_basis": "per_piece",
            f"op-{phase.pk}-notes": "",
        })
        self.assertRedirects(response, reverse("quotes:work", args=[self.quote.pk]))
        operation = TimeOperation.objects.get(phase=phase)
        self.assertEqual(operation.working_minutes, Decimal("10.50"))
        self.assertEqual(operation.setup_minutes, Decimal("1.25"))


class ItalianFormattingTests(TestCase):
    def test_shared_decimal_formatting(self):
        self.assertEqual(normalize_decimal_input("1.234,56"), "1234.56")
        self.assertEqual(normalize_decimal_input("1234.56"), "1234.56")
        self.assertEqual(format_decimal_it(Decimal("12"), 2), "12,00")
        self.assertEqual(format_money(Decimal("46.2")), "€ 46,20")
        self.assertEqual(format_weight(Decimal("12")), "12,000 kg")


class ClientAndLanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("clients", password="pass")
        cls.user.groups.add(Group.objects.get(name="Commerciale"))
        cls.superuser = get_user_model().objects.create_superuser("lan-admin", password="pass")
        cls.client_record = Client.objects.create(name="Cliente Uno")
        cls.contact = ClientContact.objects.create(
            client=cls.client_record,
            name="Mario Rossi",
            email="mario@example.com",
        )

    def test_registered_contact_fills_quote_snapshot_server_side(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("quotes:create"), {
            "date": "2026-07-22",
            "client_lookup": self.client_record.name,
            "client": self.client_record.pk,
            "contact_id": self.contact.pk,
            "client_contact": "",
            "client_email": "",
            "internal_notes": "",
            "customer_notes": "",
        })
        quote = Quote.objects.get(author=self.user)
        self.assertRedirects(response, reverse("quotes:items", args=[quote.pk]))
        self.assertEqual(quote.client_contact, "Mario Rossi")
        self.assertEqual(quote.client_email, "mario@example.com")

    def test_lan_toggle_blocks_and_allows_remote_address(self):
        self.client.force_login(self.user)
        config = SiteConfiguration.load()
        config.lan_enabled = False
        config.save()
        self.assertEqual(self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR="192.168.1.25").status_code, 403)
        config.lan_enabled = True
        config.save()
        self.assertEqual(self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR="192.168.1.25").status_code, 200)

    def test_lan_management_page_is_superuser_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("catalog:lan_settings")).status_code, 403)
        self.assertEqual(self.client.post(reverse("catalog:lan_settings"), {"lan_enabled": "on"}).status_code, 403)

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("catalog:lan_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestione rete locale")

        response = self.client.post(reverse("catalog:lan_settings"), {"lan_enabled": "on"})
        self.assertRedirects(response, reverse("catalog:lan_settings"))
        self.assertTrue(SiteConfiguration.load().lan_enabled)

        self.client.post(reverse("catalog:lan_settings"), {})
        self.assertFalse(SiteConfiguration.load().lan_enabled)

    def test_lan_link_is_visible_only_in_superuser_dashboard(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("quotes:dashboard")), reverse("catalog:lan_settings"))
        self.client.force_login(self.superuser)
        self.assertContains(self.client.get(reverse("quotes:dashboard")), reverse("catalog:lan_settings"))

    @override_settings(LAN_SCRIPT_ACTIVE=True)
    def test_lan_page_reports_script_mode(self):
        self.client.force_login(self.superuser)
        self.assertContains(self.client.get(reverse("catalog:lan_settings")), "Script LAN")

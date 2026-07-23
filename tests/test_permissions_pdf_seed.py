from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Material, PhaseDefinition, ProductionResource
from apps.quotes.models import ItemMaterial, Quote, QuoteItem, QuoteSequence
from apps.quotes.services.quotes import initialize_item_phases


class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.commercial = get_user_model().objects.create_user("commerciale", password="pass")
        cls.commercial.groups.add(Group.objects.get(name="Commerciale"))
        cls.admin_user = get_user_model().objects.create_user("amministratore", password="pass", is_staff=True)
        cls.admin_user.groups.add(Group.objects.get(name="Amministratore"))

    def test_commercial_permissions_and_no_admin_access(self):
        self.assertTrue(self.commercial.has_perm("quotes.add_quote"))
        self.assertTrue(self.commercial.has_perm("quotes.generate_quote_pdf"))
        self.assertFalse(self.commercial.has_perm("catalog.change_material"))
        self.client.force_login(self.commercial)
        self.assertEqual(self.client.get(reverse("quotes:dashboard")).status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_only_superuser_can_access_admin(self):
        self.assertTrue(self.admin_user.has_perm("catalog.change_material"))
        self.assertTrue(self.admin_user.has_perm("auth.change_user"))
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        superuser = get_user_model().objects.create_superuser("superadmin", password="pass")
        self.client.force_login(superuser)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_commercial_wizard_pages_render(self):
        material = Material.objects.create(name="Wizard material", current_cost_per_kg=Decimal("1.50"))
        quote = Quote.objects.create(author=self.commercial)
        item = QuoteItem.objects.create(quote=quote, code="WIZ-01", quantity=2)
        ItemMaterial.objects.create(item=item, material=material, weight_kg=Decimal("3"), unit_cost_snapshot=Decimal("1.50"))
        initialize_item_phases(item)
        self.client.force_login(self.commercial)
        general_response = self.client.get(reverse("quotes:general", args=[quote.pk]))
        self.assertContains(general_response, f'value="{quote.date:%Y-%m-%d}"')
        for url in (
            reverse("quotes:items", args=[quote.pk]),
            reverse("quotes:work", args=[quote.pk]), reverse("quotes:summary", args=[quote.pk]),
            reverse("quotes:search"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        phase = item.phases.get(definition__code="taglio-lamiera")
        response = self.client.post(reverse("quotes:phase_update", args=[quote.pk, phase.pk]), {
            f"phase-{phase.pk}-active": "True", f"phase-{phase.pk}-notes": "",
        })
        self.assertEqual(response.status_code, 302)
        phase.refresh_from_db()
        self.assertTrue(phase.active)


class PdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("pdfuser", password="pass")
        cls.user.groups.add(Group.objects.get(name="Commerciale"))
        material = Material.objects.create(name="PDF Steel", current_cost_per_kg=Decimal("9.99"))
        cls.quote = Quote.objects.create(author=cls.user, offered_price=Decimal("1250"), internal_notes="SEGRETO INTERNO")
        item = QuoteItem.objects.create(quote=cls.quote, code="PDF-01", quantity=2, description="Piastra")
        ItemMaterial.objects.create(item=item, material=material, weight_kg=Decimal("5"), unit_cost_snapshot=Decimal("9.99"))

    def test_pdf_generation_and_customer_filename(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:pdf", args=[self.quote.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(self.quote.number, response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_does_not_expose_internal_economic_labels(self):
        self.client.force_login(self.user)
        content = self.client.get(reverse("quotes:pdf", args=[self.quote.pk])).content.lower()
        for forbidden in (b"costo orario", b"operatori", b"margine", b"costo industriale", b"segreto interno"):
            self.assertNotIn(forbidden, content)


class SequenceAndSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sequence", password="pass")

    def test_progressive_quote_number(self):
        first = Quote.objects.create(author=self.user)
        second = Quote.objects.create(author=self.user)
        self.assertRegex(first.number, r"^PR-\d{4}-00001$")
        self.assertTrue(second.number.endswith("-00002"))
        self.assertEqual(QuoteSequence.objects.count(), 1)

    def test_seed_is_idempotent(self):
        call_command("seed_initial_data", verbosity=0)
        counts = (PhaseDefinition.objects.count(), ProductionResource.objects.count(), Group.objects.filter(name__in=["Commerciale", "Amministratore"]).count())
        call_command("seed_initial_data", verbosity=0)
        self.assertEqual(counts, (PhaseDefinition.objects.count(), ProductionResource.objects.count(), Group.objects.filter(name__in=["Commerciale", "Amministratore"]).count()))
        self.assertEqual(counts, (11, 17, 2))

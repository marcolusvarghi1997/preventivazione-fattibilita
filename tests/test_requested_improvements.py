from decimal import Decimal
from pathlib import Path
import signal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Client, ClientContact, LanDeviceAccess, Material, PhaseDefinition, ProductionResource
from apps.catalog.network import get_lan_ipv4_addresses, get_remote_mac, normalize_mac
from apps.quotes.formatting import format_decimal_it, format_money, format_weight, normalize_decimal_input
from apps.quotes.forms import (
    DirectCostForm,
    ItalianDecimalField,
    ItemMaterialEditForm,
    ItemMaterialForm,
    QuoteItemForm,
    QuoteSearchForm,
    QuoteSummaryForm,
    TimeOperationForm,
    TreatmentForm,
)
from apps.quotes.models import Feasibility, ItemMaterial, ItemPhase, Quote, QuoteItem, TimeOperation
from config.lan_server import enable_console_ctrl_c, run as run_lan_server, stop_confirmed


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
        article = QuoteItem.objects.create(quote=self.other_quote, code="PRESERVATO", revision="00")
        self.client.force_login(superuser)
        response = self.client.post(reverse("quotes:delete", args=[self.other_quote.pk]))
        self.assertRedirects(response, reverse("quotes:dashboard"))
        self.assertFalse(Quote.objects.filter(pk=self.other_quote.pk).exists())
        article.refresh_from_db()
        self.assertIsNone(article.quote)

    def test_preventivi_root_points_to_dashboard(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/preventivi/").status_code, 200)

    def test_dashboard_is_paginated_at_twenty_rows(self):
        for _ in range(20):
            Quote.objects.create(author=self.owner)
        self.client.force_login(self.owner)

        first_page = self.client.get(reverse("quotes:dashboard"))
        second_page = self.client.get(reverse("quotes:dashboard"), {"page": 2})

        self.assertEqual(first_page.context["page"].paginator.per_page, 20)
        self.assertEqual(len(first_page.context["quotes"]), 20)
        self.assertTrue(first_page.context["page"].has_next())
        self.assertEqual(len(second_page.context["quotes"]), 1)

    def test_search_is_paginated_at_fifty_rows(self):
        for _ in range(50):
            Quote.objects.create(author=self.owner)
        self.client.force_login(self.owner)

        first_page = self.client.get(reverse("quotes:search"))
        second_page = self.client.get(reverse("quotes:search"), {"page": 2})

        self.assertEqual(first_page.context["page"].paginator.per_page, 50)
        self.assertEqual(len(first_page.context["page"].object_list), 50)
        self.assertTrue(first_page.context["page"].has_next())
        self.assertEqual(len(second_page.context["page"].object_list), 1)

    def test_dashboard_columns_are_sortable(self):
        Quote.objects.create(author=self.owner, number="AAA")
        Quote.objects.create(author=self.owner, number="ZZZ")
        self.client.force_login(self.owner)

        response = self.client.get(reverse("quotes:dashboard"), {"sort": "number", "dir": "asc"})

        numbers = [quote.number for quote in response.context["quotes"]]
        self.assertEqual(numbers, sorted(numbers))
        self.assertContains(response, 'aria-sort="ascending"', html=False)

    def test_search_sorts_by_first_article_code(self):
        first = Quote.objects.create(author=self.owner, number="SORT-1")
        second = Quote.objects.create(author=self.owner, number="SORT-2")
        QuoteItem.objects.create(quote=first, code="ZZZ")
        QuoteItem.objects.create(quote=second, code="AAA")
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("quotes:search"),
            {"q": "SORT-", "sort": "articles", "dir": "asc"},
        )

        self.assertEqual([quote.pk for quote in response.context["page"]], [second.pk, first.pk])

    def test_quote_rows_show_colored_feasibility_and_open_as_a_whole(self):
        Quote.objects.create(author=self.owner, feasibility=Feasibility.INTERNAL)
        Quote.objects.create(author=self.owner, feasibility=Feasibility.NOT_FEASIBLE)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("quotes:dashboard"))

        self.assertContains(response, "feasibility-text internal")
        self.assertContains(response, "feasibility-text to-check")
        self.assertContains(response, "feasibility-text not-feasible")
        self.assertContains(response, 'data-row-href="', html=False)
        self.assertNotContains(response, ">Apri</a>", html=False)

    def test_dashboard_exposes_only_bulk_archiving(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("quotes:dashboard"))

        self.assertContains(response, 'name="quote_ids"', html=False)
        self.assertContains(response, "Archivia multipli")
        self.assertContains(response, "Archivia selezionati")
        self.assertContains(response, "Archivia tutti")
        self.assertContains(response, "data-bulk-only hidden", html=False)
        self.assertNotContains(response, "Elimina selezionati")
        self.assertContains(response, reverse("quotes:bulk_archive"))

    def test_bulk_archive_updates_only_selected_visible_quotes(self):
        second_selected = Quote.objects.create(author=self.owner)
        unselected = Quote.objects.create(author=self.owner)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("quotes:bulk_archive"),
            {
                "scope": "selected",
                "quote_ids": [
                    str(self.owner_quote.pk),
                    str(second_selected.pk),
                    str(self.other_quote.pk),
                ]
            },
            follow=True,
        )

        self.owner_quote.refresh_from_db()
        second_selected.refresh_from_db()
        unselected.refresh_from_db()
        self.other_quote.refresh_from_db()
        self.assertEqual(self.owner_quote.status, Quote.Status.ARCHIVED)
        self.assertEqual(second_selected.status, Quote.Status.ARCHIVED)
        self.assertEqual(self.owner_quote.status_before_archive, Quote.Status.DRAFT)
        self.assertEqual(second_selected.status_before_archive, Quote.Status.DRAFT)
        self.assertNotEqual(unselected.status, Quote.Status.ARCHIVED)
        self.assertNotEqual(self.other_quote.status, Quote.Status.ARCHIVED)
        self.assertTrue(Quote.objects.filter(pk=self.owner_quote.pk).exists())
        self.assertContains(response, "2 preventivi archiviati")

    def test_bulk_archive_without_selection_does_not_change_quotes(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("quotes:bulk_archive"), follow=True)

        self.owner_quote.refresh_from_db()
        self.assertNotEqual(self.owner_quote.status, Quote.Status.ARCHIVED)
        self.assertContains(response, "Seleziona almeno un preventivo")

    def test_bulk_archive_accepts_only_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("quotes:bulk_archive")).status_code, 405)

    def test_archive_all_archives_every_visible_active_quote_and_keeps_previous_status(self):
        completed = Quote.objects.create(author=self.owner, status=Quote.Status.COMPLETED)
        rejected = Quote.objects.create(author=self.owner, status=Quote.Status.REJECTED)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("quotes:bulk_archive"),
            {"scope": "all"},
            follow=True,
        )

        self.owner_quote.refresh_from_db()
        completed.refresh_from_db()
        rejected.refresh_from_db()
        self.other_quote.refresh_from_db()
        self.assertEqual(self.owner_quote.status_before_archive, Quote.Status.DRAFT)
        self.assertEqual(completed.status_before_archive, Quote.Status.COMPLETED)
        self.assertEqual(rejected.status_before_archive, Quote.Status.REJECTED)
        self.assertTrue(all(
            quote.status == Quote.Status.ARCHIVED
            for quote in (self.owner_quote, completed, rejected)
        ))
        self.assertNotEqual(self.other_quote.status, Quote.Status.ARCHIVED)
        self.assertContains(response, "3 preventivi archiviati")

    def test_archived_status_is_not_displayed_or_filtered_as_draft(self):
        archived = Quote.objects.create(
            author=self.owner,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.COMPLETED,
            customer_decision=Quote.CustomerDecision.ACCEPTED,
        )
        self.client.force_login(self.owner)

        archived_response = self.client.get(
            reverse("quotes:search"),
            {"status": Quote.Status.ARCHIVED},
        )
        draft_response = self.client.get(
            reverse("quotes:search"),
            {"status": Quote.Status.DRAFT},
        )

        self.assertEqual(archived.display_status, "Archiviato")
        self.assertEqual(archived.status_css_class, "archived")
        self.assertContains(archived_response, archived.number)
        self.assertContains(archived_response, "Archiviato")
        self.assertNotContains(draft_response, archived.number)

    def test_bulk_restore_restores_only_selected_own_quotes(self):
        completed = Quote.objects.create(
            author=self.owner,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.COMPLETED,
        )
        rejected = Quote.objects.create(
            author=self.owner,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.REJECTED,
        )
        other_archived = Quote.objects.create(
            author=self.other,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.COMPLETED,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("quotes:bulk_restore"),
            {
                "scope": "selected",
                "quote_ids": [str(completed.pk), str(other_archived.pk)],
            },
            follow=True,
        )

        completed.refresh_from_db()
        rejected.refresh_from_db()
        other_archived.refresh_from_db()
        self.assertEqual(completed.status, Quote.Status.COMPLETED)
        self.assertEqual(completed.status_before_archive, "")
        self.assertEqual(rejected.status, Quote.Status.ARCHIVED)
        self.assertEqual(other_archived.status, Quote.Status.ARCHIVED)
        self.assertContains(response, "1 preventivo ripristinato")

    def test_restore_all_respects_current_search_filters(self):
        matching = Quote.objects.create(
            author=self.owner,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.COMPLETED,
        )
        not_matching = Quote.objects.create(
            author=self.owner,
            status=Quote.Status.ARCHIVED,
            status_before_archive=Quote.Status.REJECTED,
        )
        self.client.force_login(self.owner)

        self.client.post(
            f"{reverse('quotes:bulk_restore')}?q={matching.number}",
            {"scope": "all"},
        )

        matching.refresh_from_db()
        not_matching.refresh_from_db()
        self.assertEqual(matching.status, Quote.Status.COMPLETED)
        self.assertEqual(not_matching.status, Quote.Status.ARCHIVED)


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
            revision="00",
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

    def test_every_economic_form_uses_the_shared_dot_and_comma_decimal_field(self):
        forms = (
            QuoteSummaryForm(),
            QuoteItemForm(),
            ItemMaterialForm(),
            ItemMaterialEditForm(),
            TimeOperationForm(),
            DirectCostForm(),
            TreatmentForm(),
        )
        decimal_fields = [
            field
            for form in forms
            for field in form.fields.values()
            if isinstance(field, ItalianDecimalField)
        ]
        self.assertEqual(len(decimal_fields), 15)
        for field in decimal_fields:
            with self.subTest(label=field.label):
                self.assertEqual(field.clean("12,5"), field.clean("12.5"))
                self.assertEqual(field.clean("12,5"), Decimal("12.5"))

    def test_feasibility_choices_use_green_yellow_red_order(self):
        expected = [
            ("internal", "Fattibile internamente"),
            ("to_check", "Da verificare"),
            ("not_feasible", "Non fattibile"),
        ]
        self.assertEqual(list(QuoteItemForm().fields["feasibility"].choices), expected)
        self.assertEqual(list(QuoteSummaryForm().fields["feasibility"].choices), expected)
        self.assertEqual(list(QuoteSearchForm().fields["feasibility"].choices)[1:], expected)
        self.assertEqual(QuoteItem().feasibility, Feasibility.TO_CHECK)

    def test_material_editor_shows_units_without_repeating_current_values(self):
        response = self.client.get(reverse("quotes:items", args=[self.quote.pk]))
        self.assertContains(response, "material-value-control")
        self.assertContains(response, "Peso per pezzo")
        self.assertContains(response, "Costo al kg")
        self.assertNotContains(response, 'class="current-value"', html=False)

    def test_work_page_separates_production_optional_and_required_fields(self):
        definition = PhaseDefinition.objects.get(code="taglio-lamiera")
        ItemPhase.objects.create(item=self.item, definition=definition, active=True, display_order=1)
        response = self.client.get(reverse("quotes:work", args=[self.quote.pk]))
        self.assertContains(response, "Fasi di produzione")
        self.assertContains(response, "Lavorazioni e costi aggiuntivi")
        self.assertContains(response, "Dati necessari")
        self.assertContains(response, "Dettagli facoltativi")
        self.assertContains(response, "Vai al riepilogo")
        self.assertContains(response, "phase-grid--production")
        self.assertContains(response, "phase-grid--additional")

    def test_external_purchase_form_marks_the_economic_cost_as_required(self):
        definition = PhaseDefinition.objects.get(code="acquisti-esterni")
        phase = ItemPhase.objects.create(item=self.item, definition=definition, display_order=10)
        form = DirectCostForm(phase=phase)
        self.assertTrue(form.fields["amount"].required)
        self.assertEqual(form.fields["amount"].label, "Costo acquisto")

    def test_disabled_supplementary_cost_is_preserved_but_not_calculated(self):
        form = QuoteItemForm(data={
            "code": self.item.code,
            "quantity": self.item.quantity,
            "description": self.item.description,
            "revision": self.item.revision,
            "length_mm": "120,5",
            "height_mm": "80",
            "depth_mm": "",
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
            preferred=True,
        )

    def setUp(self):
        self.detected_mac = "02:11:22:33:44:55"
        self.mac_patcher = patch(
            "apps.catalog.middleware.get_remote_mac",
            return_value=self.detected_mac,
        )
        self.mocked_remote_mac = self.mac_patcher.start()
        self.addCleanup(self.mac_patcher.stop)

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

    def test_client_can_have_only_one_preferred_contact(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ClientContact.objects.create(
                    client=self.client_record,
                    name="Altro preferito",
                    preferred=True,
                )

    def test_general_page_uses_only_registered_contacts(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:create"))
        self.assertContains(response, "L’elenco contiene solo i referenti del cliente selezionato.")
        self.assertContains(response, "Nuovo referente")
        self.assertNotContains(response, "Inserimento libero")
        self.assertNotContains(response, "Cliente selezionato:")
        self.assertContains(response, 'name="client_contact"', html=False)
        self.assertContains(response, 'type="hidden"', html=False)

    def test_wizard_forward_navigation_does_not_show_a_confirmation_banner(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("quotes:create"), {
            "date": "2026-07-23",
            "client_lookup": self.client_record.name,
            "client": self.client_record.pk,
            "contact_id": self.contact.pk,
            "client_contact": "",
            "client_email": "",
            "internal_notes": "",
            "customer_notes": "",
        }, follow=True)
        self.assertNotContains(response, "Dati generali salvati.")
        self.assertNotContains(response, "toast-region")

    def test_articles_page_separates_essential_and_optional_information(self):
        quote = Quote.objects.create(author=self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:items", args=[quote.pk]))
        self.assertContains(response, "<h1>2. Articoli</h1>", html=True)
        self.assertContains(response, "sticky-actions wizard-actions")
        self.assertContains(response, "Prima fase")
        self.assertContains(response, "Carica articolo")
        self.assertNotContains(response, "Dettagli tecnici aggiuntivi")
        self.assertNotContains(response, "Costi supplementari facoltativi")
        self.assertNotContains(response, "article-core-fields")
        self.assertNotContains(response, "article-description-panel")

        item = QuoteItem.objects.create(quote=quote, code="CARICATO-01", revision="00")
        loaded_response = self.client.get(reverse("quotes:items", args=[quote.pk]))
        self.assertContains(loaded_response, "Dettagli tecnici aggiuntivi")
        self.assertContains(loaded_response, "Costi supplementari facoltativi")
        self.assertContains(loaded_response, "Articolo caricato")
        self.assertNotContains(loaded_response, "Seconda fase ·")
        self.assertContains(loaded_response, "Converti misure")
        self.assertContains(loaded_response, f'name="item-{item.pk}-length_mm"', html=False)
        self.assertContains(loaded_response, f'name="item-{item.pk}-height_mm"', html=False)
        self.assertContains(loaded_response, f'name="item-{item.pk}-depth_mm"', html=False)
        self.assertContains(loaded_response, "Materiali del pezzo")
        self.assertContains(loaded_response, "article-core-fields")
        self.assertContains(loaded_response, "article-description-panel")
        self.assertContains(loaded_response, f'name="item-{item.pk}-description"', html=False)
        self.assertNotContains(loaded_response, "(non conteggiato)")
        work_response = self.client.get(reverse("quotes:work", args=[quote.pk]))
        self.assertContains(
            work_response,
            "<h1>3. Lavorazioni</h1>",
            html=True,
        )
        self.assertContains(work_response, "sticky-actions wizard-actions")
        summary_response = self.client.get(reverse("quotes:summary", args=[quote.pk]))
        self.assertContains(
            summary_response,
            "<h1>4. Riepilogo e Fattibilità</h1>",
            html=True,
        )
        self.assertContains(summary_response, "sticky-actions wizard-actions wizard-actions--single")

    def test_edit_page_restores_the_registered_contact(self):
        quote = Quote.objects.create(
            author=self.user,
            client=self.client_record,
            client_contact=self.contact.name,
            client_email=self.contact.email,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:general", args=[quote.pk]))
        self.assertContains(response, f"Preventivo {quote.number}")
        self.assertContains(response, "<h1>1. Dati generali</h1>", html=True)
        self.assertContains(response, "Cliente, referente e note generali del preventivo.")
        self.assertContains(response, "general-workspace")
        self.assertContains(response, "sticky-actions wizard-actions")
        self.assertContains(response, 'form="quote-general-form"', html=False)
        self.assertContains(response, f'name="contact_id" value="{self.contact.pk}"', html=False)
        self.assertContains(response, f'value="{self.client_record.name}"', html=False)

    def test_quick_contact_is_linked_to_selected_client(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("quotes:client_contact_quick_add"), {
            "quick-contact-client": self.client_record.pk,
            "quick-contact-name": "Luisa Bianchi",
            "quick-contact-email": "luisa@example.com",
            "quick-contact-phone": "02 123456",
        })
        self.assertEqual(response.status_code, 200)
        contact = ClientContact.objects.get(name="Luisa Bianchi")
        self.assertEqual(contact.client, self.client_record)
        self.assertEqual(response.json()["contact"]["client_id"], self.client_record.pk)

    def test_quick_contact_rejects_case_insensitive_duplicates_for_same_client(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("quotes:client_contact_quick_add"), {
            "quick-contact-client": self.client_record.pk,
            "quick-contact-name": "mario rossi",
            "quick-contact-email": "diversa@example.com",
            "quick-contact-phone": "",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("già un referente", response.json()["errors"]["name"][0])

        response = self.client.post(reverse("quotes:client_contact_quick_add"), {
            "quick-contact-client": self.client_record.pk,
            "quick-contact-name": "Nome Diverso",
            "quick-contact-email": "MARIO@example.com",
            "quick-contact-phone": "",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("già associata", response.json()["errors"]["email"][0])

    def test_unselected_contact_cannot_be_supplied_as_free_text(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("quotes:create"), {
            "date": "2026-07-23",
            "client_lookup": self.client_record.name,
            "client": self.client_record.pk,
            "contact_id": "",
            "client_contact": "Referente inventato",
            "client_email": "inventato@example.com",
            "internal_notes": "",
            "customer_notes": "",
        })
        quote = Quote.objects.get(author=self.user)
        self.assertRedirects(response, reverse("quotes:items", args=[quote.pk]))
        self.assertEqual(quote.client_contact, "")
        self.assertEqual(quote.client_email, "")

    def test_lan_request_is_detected_and_access_follows_ip_and_mac_decision(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR="192.168.1.25")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Richiesta inviata al superadmin", status_code=403)

        device = LanDeviceAccess.objects.get(ip_address="192.168.1.25")
        self.assertEqual(device.status, LanDeviceAccess.Status.PENDING)
        self.assertEqual(device.mac_address, self.detected_mac)
        device.status = LanDeviceAccess.Status.ALLOWED
        device.save(update_fields=("status",))
        self.assertEqual(self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR="192.168.1.25").status_code, 200)

        device.status = LanDeviceAccess.Status.DENIED
        device.save(update_fields=("status",))
        response = self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR="192.168.1.25")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Questo PC non è autorizzato", status_code=403)

    def test_console_stop_requires_one_server_confirmation(self):
        handlers = {}

        class FakeServer:
            def __init__(self):
                self.closed = False

            def run(self):
                try:
                    handlers[signal.SIGINT](signal.SIGINT, None)
                except SystemExit:
                    pass

            def close(self):
                self.closed = True

        fake_server = FakeServer()

        def register_handler(signal_number, handler):
            handlers[signal_number] = handler

        with (
            patch("waitress.create_server", return_value=fake_server),
            patch("config.lan_server.enable_console_ctrl_c"),
            patch("config.lan_server.signal.signal", side_effect=register_handler),
            patch("builtins.input", return_value="s"),
        ):
            self.assertEqual(run_lan_server(), 130)
        self.assertTrue(fake_server.closed)

        batch = Path("scripts/start_lan.bat").read_text(encoding="utf-8")
        self.assertIn('start "" /b ".venv\\Scripts\\python.exe" -m config.lan_server', batch)
        self.assertNotIn("/wait", batch.casefold())
        self.assertNotIn("choice ", batch.casefold())

    def test_rejected_console_stop_keeps_server_running_until_confirmed(self):
        self.assertTrue(stop_confirmed("s"))
        self.assertTrue(stop_confirmed("sì"))
        self.assertFalse(stop_confirmed("n"))
        self.assertFalse(stop_confirmed(""))

        handlers = {}
        states_after_each_answer = []

        class FakeServer:
            def __init__(self):
                self.closed = False

            def run(self):
                handlers[signal.SIGINT](signal.SIGINT, None)
                states_after_each_answer.append(self.closed)
                try:
                    handlers[signal.SIGINT](signal.SIGINT, None)
                except SystemExit:
                    pass

            def close(self):
                self.closed = True

        fake_server = FakeServer()
        with (
            patch("waitress.create_server", return_value=fake_server),
            patch("config.lan_server.enable_console_ctrl_c"),
            patch(
                "config.lan_server.signal.signal",
                side_effect=lambda signal_number, handler: handlers.__setitem__(signal_number, handler),
            ),
            patch("builtins.input", side_effect=("n", "s")),
        ):
            self.assertEqual(run_lan_server(), 130)
        self.assertEqual(states_after_each_answer, [False])
        self.assertTrue(fake_server.closed)

    def test_console_ctrl_c_enablement_is_safe_outside_windows(self):
        with patch("config.lan_server.os.name", "posix"):
            self.assertIsNone(enable_console_ctrl_c())

    def test_lan_request_is_detected_on_company_network_with_public_ipv4(self):
        remote_ip = "194.150.150.50"
        self.client.force_login(self.user)
        response = self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR=remote_ip)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(LanDeviceAccess.objects.filter(ip_address=remote_ip).exists())

    def test_pending_anonymous_ip_cannot_open_or_submit_login(self):
        remote_ip = "194.150.150.55"
        remote_client = self.client_class()

        self.assertEqual(
            remote_client.get(reverse("quotes:dashboard"), REMOTE_ADDR=remote_ip).status_code,
            403,
        )
        device = LanDeviceAccess.objects.get(ip_address=remote_ip)
        self.assertEqual(device.status, LanDeviceAccess.Status.PENDING)
        self.assertEqual(
            remote_client.get(reverse("login"), REMOTE_ADDR=remote_ip).status_code,
            403,
        )
        self.assertEqual(
            remote_client.get(reverse("admin:login"), REMOTE_ADDR=remote_ip).status_code,
            403,
        )
        denied_login = remote_client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
            REMOTE_ADDR=remote_ip,
        )
        self.assertEqual(denied_login.status_code, 403)
        self.assertNotIn("_auth_user_id", remote_client.session)

    def test_lan_management_page_is_superuser_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("catalog:lan_settings")).status_code, 403)

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("catalog:lan_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestione rete locale")

    def test_superuser_can_allow_and_revoke_a_detected_ip(self):
        device = LanDeviceAccess.objects.create(
            ip_address="192.168.1.40",
            mac_address=self.detected_mac,
            last_seen_at="2026-07-23T08:00:00Z",
        )
        decision_url = reverse("catalog:decide_lan_access", args=[device.pk])

        self.client.force_login(self.user)
        self.assertEqual(self.client.post(decision_url, {"decision": "allow"}).status_code, 403)

        self.client.force_login(self.superuser)
        self.assertRedirects(
            self.client.post(decision_url, {"decision": "allow"}),
            reverse("catalog:lan_settings"),
        )
        device.refresh_from_db()
        self.assertEqual(device.status, LanDeviceAccess.Status.ALLOWED)
        self.assertEqual(device.decided_by, self.superuser)

        self.client.post(decision_url, {"decision": "deny"})
        device.refresh_from_db()
        self.assertEqual(device.status, LanDeviceAccess.Status.DENIED)

    def test_revoked_anonymous_ip_cannot_open_or_submit_login(self):
        remote_ip = "194.150.150.61"
        device = LanDeviceAccess.objects.create(
            ip_address=remote_ip,
            mac_address=self.detected_mac,
            status=LanDeviceAccess.Status.ALLOWED,
            last_seen_at="2026-07-23T08:00:00Z",
        )
        remote_client = self.client_class()

        login_response = remote_client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
            REMOTE_ADDR=remote_ip,
        )
        self.assertEqual(login_response.status_code, 302)
        remote_client.post(reverse("logout"), REMOTE_ADDR=remote_ip)

        self.client.force_login(self.superuser)
        self.client.post(
            reverse("catalog:decide_lan_access", args=[device.pk]),
            {"decision": "deny"},
        )
        device.refresh_from_db()
        self.assertEqual(device.status, LanDeviceAccess.Status.DENIED)

        self.assertEqual(
            remote_client.get(reverse("login"), REMOTE_ADDR=remote_ip).status_code,
            403,
        )
        denied_login = remote_client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
            REMOTE_ADDR=remote_ip,
        )
        self.assertEqual(denied_login.status_code, 403)
        self.assertNotIn("_auth_user_id", remote_client.session)

    def test_superuser_can_remove_a_lan_request(self):
        device = LanDeviceAccess.objects.create(
            ip_address="194.150.150.62",
            last_seen_at="2026-07-23T08:00:00Z",
        )
        delete_url = reverse("catalog:delete_lan_access", args=[device.pk])

        self.client.force_login(self.user)
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertRedirects(self.client.post(delete_url), reverse("catalog:lan_settings"))
        self.assertFalse(LanDeviceAccess.objects.filter(pk=device.pk).exists())

    def test_allow_is_rejected_until_mac_is_detected(self):
        device = LanDeviceAccess.objects.create(
            ip_address="192.168.1.63",
            last_seen_at="2026-07-23T08:00:00Z",
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("catalog:decide_lan_access", args=[device.pk]),
            {"decision": "allow"},
            follow=True,
        )

        device.refresh_from_db()
        self.assertEqual(device.status, LanDeviceAccess.Status.PENDING)
        self.assertContains(response, "non può essere autorizzato finché il MAC non viene rilevato")

    def test_changed_mac_resets_an_allowed_ip_to_pending(self):
        remote_ip = "192.168.1.64"
        device = LanDeviceAccess.objects.create(
            ip_address=remote_ip,
            mac_address=self.detected_mac,
            status=LanDeviceAccess.Status.ALLOWED,
            last_seen_at="2026-07-23T08:00:00Z",
            decided_at="2026-07-23T08:05:00Z",
            decided_by=self.superuser,
        )
        changed_mac = "02:AA:BB:CC:DD:EE"

        with patch("apps.catalog.middleware.get_remote_mac", return_value=changed_mac):
            response = self.client.get(reverse("login"), REMOTE_ADDR=remote_ip)

        self.assertEqual(response.status_code, 403)
        device.refresh_from_db()
        self.assertEqual(device.mac_address, changed_mac)
        self.assertEqual(device.status, LanDeviceAccess.Status.PENDING)
        self.assertIsNone(device.decided_at)
        self.assertIsNone(device.decided_by)

    def test_allowed_ip_is_blocked_when_mac_cannot_be_verified(self):
        remote_ip = "192.168.1.65"
        LanDeviceAccess.objects.create(
            ip_address=remote_ip,
            mac_address=self.detected_mac,
            status=LanDeviceAccess.Status.ALLOWED,
            last_seen_at="2026-07-23T08:00:00Z",
        )

        with patch("apps.catalog.middleware.get_remote_mac", return_value=None):
            response = self.client.get(
                reverse("login"),
                REMOTE_ADDR=remote_ip,
                HTTP_X_DEVICE_MAC=self.detected_mac,
            )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Identità di rete non verificabile", status_code=403)
        self.assertContains(response, "Non disponibile", status_code=403)

    def test_remote_superuser_can_open_lan_management_without_prior_approval(self):
        remote_ip = "192.168.1.77"
        self.client.force_login(self.superuser)
        self.assertFalse(LanDeviceAccess.objects.filter(ip_address=remote_ip).exists())
        self.assertEqual(
            self.client.get(reverse("catalog:lan_settings"), REMOTE_ADDR=remote_ip).status_code,
            200,
        )
        self.assertTrue(LanDeviceAccess.objects.filter(ip_address=remote_ip).exists())
        self.assertEqual(
            self.client.get(reverse("quotes:dashboard"), REMOTE_ADDR=remote_ip).status_code,
            403,
        )

    @patch("apps.catalog.network.get_lan_ipv4_addresses", return_value=["192.168.1.10"])
    def test_lan_page_shows_readonly_server_network_info(self, mocked_addresses):
        LanDeviceAccess.objects.create(
            ip_address="192.168.1.80",
            mac_address=self.detected_mac,
            last_seen_at="2026-07-23T08:00:00Z",
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("catalog:lan_settings"), HTTP_HOST="server.test:8765", SERVER_PORT="8765")
        self.assertContains(response, "Informazioni di rete in sola lettura")
        self.assertContains(response, "IP del server")
        self.assertContains(response, "192.168.1.10")
        self.assertContains(response, "<code>8765</code>", html=True)
        self.assertContains(response, "http://192.168.1.10:8765")
        self.assertContains(response, "Indirizzo MAC")
        self.assertContains(response, "IP + MAC")

    def test_dashboard_does_not_show_lan_data(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("quotes:dashboard"))
        self.assertNotContains(response, "Collegamento per gli altri PC")
        self.assertNotContains(response, "Nessuna richiesta")

    def test_lan_management_uses_admin_rete_url_only(self):
        self.assertEqual(reverse("catalog:lan_settings"), "/admin/rete/")
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get("/admin/rete/").status_code, 200)
        self.assertEqual(self.client.get("/superadmin/rete/").status_code, 404)

    @patch("apps.catalog.network.socket.socket", side_effect=OSError)
    @patch("apps.catalog.network.socket.getaddrinfo")
    def test_public_ipv4_assigned_to_server_interface_is_not_discarded(self, mocked_getaddrinfo, mocked_socket):
        mocked_getaddrinfo.return_value = [
            (2, 1, 6, "", ("194.150.150.33", 0)),
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        self.assertEqual(get_lan_ipv4_addresses(), ["194.150.150.33"])

    @patch("apps.catalog.network.subprocess.run")
    def test_remote_mac_is_read_from_server_neighbor_table(self, mocked_run):
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = (
            "\n  Indirizzo Internet      Indirizzo fisico      Tipo\n"
            "  192.168.1.70            02-aa-bb-cc-dd-ee     dinamico\n"
        )

        self.assertEqual(get_remote_mac("192.168.1.70"), "02:AA:BB:CC:DD:EE")
        self.assertEqual(mocked_run.call_args.kwargs["check"], False)
        self.assertNotIn("shell", mocked_run.call_args.kwargs)

    def test_mac_normalization_rejects_unsafe_addresses(self):
        self.assertEqual(normalize_mac("02-aa-bb-cc-dd-ee"), "02:AA:BB:CC:DD:EE")
        self.assertIsNone(normalize_mac("01:00:5E:00:00:01"))
        self.assertIsNone(normalize_mac("FF:FF:FF:FF:FF:FF"))
        self.assertIsNone(normalize_mac("non-un-mac"))

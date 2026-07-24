from datetime import timedelta
from decimal import Decimal
import importlib
from pathlib import Path
import re
import uuid

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Material, PhaseDefinition, ProductionResource
from apps.quotes.models import (
    DirectCost,
    ExternalTreatment,
    ItemMaterial,
    ItemPhase,
    Quote,
    QuoteItem,
    TimeOperation,
)
from apps.quotes.services.quotes import (
    create_article_version_from_latest,
    latest_article_version,
)


class ArticleVersioningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_superuser(
            "versioni",
            "versioni@example.test",
            "pass",
        )
        cls.material = Material.objects.create(
            name="Materiale versionato",
            current_cost_per_kg=Decimal("3.25"),
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.source_quote = Quote.objects.create(author=self.user)
        self.target_quote = Quote.objects.create(author=self.user)

    def create_complete_source(self, *, code="ART-100", revision="04"):
        item = QuoteItem.objects.create(
            quote=self.source_quote,
            code=code,
            revision=revision,
            quantity=3,
            description="Descrizione storica",
            length_mm=Decimal("100"),
            height_mm=Decimal("50"),
            depth_mm=Decimal("25"),
            technical_notes="Nota storica",
            external_purchases=True,
            external_purchases_cost=Decimal("12.30"),
        )
        ItemMaterial.objects.create(
            item=item,
            material=self.material,
            weight_kg=Decimal("2.500"),
            unit_cost_snapshot=Decimal("3.1000"),
        )
        definition = PhaseDefinition.objects.get(code="saldatura")
        phase = ItemPhase.objects.create(
            item=item,
            definition=definition,
            active=True,
            notes="Fase storica",
            display_order=definition.display_order,
            internal_answer=ItemPhase.InternalAnswer.YES,
        )
        resource = ProductionResource.objects.filter(phase=definition).first()
        TimeOperation.objects.create(
            phase=phase,
            resource=resource,
            working_minutes=Decimal("15"),
            setup_minutes=Decimal("5"),
            operators_snapshot=2,
            resource_name_snapshot="Risorsa acquisita",
            hourly_cost_snapshot=Decimal("41.5000"),
            notes="Operazione storica",
        )
        DirectCost.objects.create(
            phase=phase,
            description="Costo storico",
            supplier="Fornitore",
            amount=Decimal("9.50"),
        )
        ExternalTreatment.objects.create(
            phase=phase,
            treatment_type=ExternalTreatment.TreatmentType.PAINTING,
            description="Blu",
            supplier="Terzista",
            cost=Decimal("20"),
        )
        return item

    def new_item_payload(self, *, code="NUOVO-1", revision="00", token=None):
        return {
            "code": code,
            "revision": revision,
            "creation_token": str(token or uuid.uuid4()),
        }

    def clone_payload(self, source, *, revision=None, token=None):
        return {
            "code": source.code,
            "revision": source.revision if revision is None else revision,
            "source_version_id": str(source.pk),
            "creation_token": str(token or uuid.uuid4()),
        }

    def test_new_code_creates_first_version_and_associates_quote(self):
        response = self.client.post(
            reverse("quotes:item_add", args=[self.target_quote.pk]),
            self.new_item_payload(),
        )
        self.assertRedirects(response, reverse("quotes:items", args=[self.target_quote.pk]))
        item = self.target_quote.items.get(code="NUOVO-1")
        self.assertEqual(item.revision, "00")
        self.assertEqual(item.article_date, timezone.localdate())
        self.assertIsNone(item.source_version)
        self.assertFalse(item.materials.exists())
        self.assertTrue(item.phases.exists())

    def test_new_article_is_inserted_at_the_top_of_the_quote(self):
        previous = QuoteItem.objects.create(
            quote=self.target_quote,
            code="PRECEDENTE",
            revision="00",
            display_order=1,
        )
        response = self.client.post(
            reverse("quotes:item_add", args=[self.target_quote.pk]),
            self.new_item_payload(code="NUOVO-IN-TESTA"),
        )
        self.assertRedirects(response, reverse("quotes:items", args=[self.target_quote.pk]))
        self.assertEqual(self.target_quote.items.first().code, "NUOVO-IN-TESTA")
        previous.refresh_from_db()
        self.assertEqual(previous.display_order, 2)
        page = self.client.get(reverse("quotes:items", args=[self.target_quote.pk]))
        summaries = re.findall(
            r'<span class="article-index">(\d+)</span>\s*<span><strong>([^<]+)</strong>',
            page.content.decode(),
        )
        self.assertEqual(
            summaries[:2],
            [("02", "NUOVO-IN-TESTA"), ("01", "PRECEDENTE")],
        )

    def test_existing_code_creates_new_version_with_same_revision(self):
        source = self.create_complete_source()
        copied, created = create_article_version_from_latest(
            code=source.code,
            revision=source.revision,
            quote=self.target_quote,
        )
        self.assertTrue(created)
        self.assertNotEqual(copied.pk, source.pk)
        self.assertEqual(copied.code, source.code)
        self.assertEqual(copied.revision, source.revision)
        self.assertEqual(copied.source_version, source)
        self.assertEqual(QuoteItem.objects.filter(code=source.code, revision=source.revision).count(), 2)

    def test_loaded_copy_is_inserted_at_the_top_of_the_quote(self):
        source = self.create_complete_source()
        previous = QuoteItem.objects.create(
            quote=self.target_quote,
            code="GIÀ-PRESENTE",
            revision="00",
            display_order=1,
        )
        copied, _ = create_article_version_from_latest(
            code=source.code,
            revision=source.revision,
            quote=self.target_quote,
        )
        self.assertEqual(self.target_quote.items.first(), copied)
        previous.refresh_from_db()
        self.assertEqual(previous.display_order, 2)

    def test_clone_copies_all_mutable_children_and_snapshots(self):
        source = self.create_complete_source()
        copied, _ = create_article_version_from_latest(code=source.code, revision=source.revision, quote=self.target_quote)
        self.assertEqual(copied.description, source.description)
        self.assertEqual(copied.external_purchases_cost, source.external_purchases_cost)
        self.assertEqual(copied.materials.get().unit_cost_snapshot, Decimal("3.1000"))
        copied_phase = copied.phases.get()
        self.assertNotEqual(copied_phase.pk, source.phases.get().pk)
        self.assertEqual(copied_phase.operations.get().hourly_cost_snapshot, Decimal("41.5000"))
        self.assertEqual(copied_phase.direct_costs.get().amount, Decimal("9.50"))
        self.assertEqual(copied_phase.treatments.get().cost, Decimal("20"))

    def test_loaded_copy_gets_the_current_date(self):
        source = self.create_complete_source()
        QuoteItem.objects.filter(pk=source.pk).update(article_date=timezone.localdate() - timedelta(days=1))
        source.refresh_from_db()
        copied, _ = create_article_version_from_latest(code=source.code, revision=source.revision, quote=self.target_quote)
        self.assertEqual(copied.article_date, timezone.localdate())
        self.assertGreater(copied.article_date, source.article_date)

    def test_editing_new_version_does_not_change_previous_version(self):
        source = self.create_complete_source()
        copied, _ = create_article_version_from_latest(code=source.code, revision=source.revision, quote=self.target_quote)
        copied.description = "Descrizione modificata"
        copied.revision = "05"
        copied.save(update_fields=["description", "revision"])
        copied.materials.update(weight_kg=Decimal("8"))
        source.refresh_from_db()
        self.assertEqual(source.description, "Descrizione storica")
        self.assertEqual(source.revision, "04")
        self.assertEqual(source.materials.get().weight_kg, Decimal("2.500"))

    def test_later_quote_uses_updated_costs_and_times_without_changing_old_quote(self):
        source = self.create_complete_source()
        current, _ = create_article_version_from_latest(
            code=source.code,
            revision=source.revision,
            quote=self.target_quote,
        )
        current_material = current.materials.get()
        current_material.unit_cost_snapshot = Decimal("4.7500")
        current_material.save(update_fields=["unit_cost_snapshot"])
        current_operation = current.phases.get().operations.get()
        current_operation.working_minutes = Decimal("28")
        current_operation.hourly_cost_snapshot = Decimal("52.0000")
        current_operation.save(update_fields=["working_minutes", "hourly_cost_snapshot"])

        later_quote = Quote.objects.create(author=self.user)
        later, _ = create_article_version_from_latest(
            code=source.code,
            revision=source.revision,
            quote=later_quote,
        )

        self.assertEqual(later.source_version, current)
        self.assertEqual(later.materials.get().unit_cost_snapshot, Decimal("4.7500"))
        self.assertEqual(later.phases.get().operations.get().working_minutes, Decimal("28"))
        self.assertEqual(later.phases.get().operations.get().hourly_cost_snapshot, Decimal("52.0000"))
        self.assertEqual(source.materials.get().unit_cost_snapshot, Decimal("3.1000"))
        self.assertEqual(source.phases.get().operations.get().working_minutes, Decimal("15"))

    def test_page_three_loads_the_specific_copied_version(self):
        source = self.create_complete_source()
        copied, _ = create_article_version_from_latest(code=source.code, revision=source.revision, quote=self.target_quote)
        response = self.client.get(reverse("quotes:work", args=[self.target_quote.pk]))
        self.assertContains(response, copied.code)
        self.assertContains(response, "Risorsa acquisita")
        self.assertNotContains(response, "versione #")

    def test_multiple_articles_in_one_quote_point_to_distinct_rows(self):
        first_source = self.create_complete_source(code="ART-A")
        second_source = self.create_complete_source(code="ART-B")
        first, _ = create_article_version_from_latest(code=first_source.code, revision=first_source.revision, quote=self.target_quote)
        second, _ = create_article_version_from_latest(code=second_source.code, revision=second_source.revision, quote=self.target_quote)
        self.assertEqual(self.target_quote.items.count(), 2)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual({first.source_version_id, second.source_version_id}, {first_source.pk, second_source.pk})

    def test_latest_article_uses_date_then_primary_key(self):
        first = self.create_complete_source()
        other_quote = Quote.objects.create(author=self.user)
        second = QuoteItem.objects.create(quote=other_quote, code=first.code, revision=first.revision)
        same_date = timezone.localdate() - timedelta(days=1)
        QuoteItem.objects.filter(pk__in=[first.pk, second.pk]).update(article_date=same_date)
        self.assertGreater(second.pk, first.pk)
        self.assertEqual(latest_article_version(first.code, first.revision), second)

    def test_lookup_reports_existing_new_missing_and_already_added(self):
        source = self.create_complete_source()
        newer_quote = Quote.objects.create(author=self.user)
        newer = QuoteItem.objects.create(
            quote=newer_quote,
            code=source.code,
            revision=source.revision,
        )
        QuoteItem.objects.create(quote=newer_quote, code=source.code, revision="05")
        url = reverse("quotes:item_latest_version", args=[self.target_quote.pk])
        existing = self.client.get(url, {"code": source.code, "revision": source.revision}).json()
        missing = self.client.get(url, {"code": "INESISTENTE", "revision": "00"}).json()
        self.assertEqual(len(existing["results"]), 2)
        revision_04 = next(row for row in existing["results"] if row["revision"] == "04")
        self.assertEqual(revision_04["id"], newer.pk)
        self.assertEqual(revision_04["article_date"], newer.article_date.isoformat())
        self.assertEqual(revision_04["article_date_display"], newer.article_date.strftime("%d/%m/%Y"))
        self.assertEqual(missing["results"], [])
        create_article_version_from_latest(code=source.code, revision=source.revision, quote=self.target_quote)
        refreshed = self.client.get(url, {"code": source.code}).json()["results"]
        self.assertTrue(next(row for row in refreshed if row["revision"] == "04")["already_added"])

    def test_lookup_matches_a_fragment_inside_the_code(self):
        source = self.create_complete_source(code="TRV-2026-ALFA-002")
        response = self.client.get(
            reverse("quotes:item_latest_version", args=[self.target_quote.pk]),
            {"code": "2026-ALFA"},
        )
        self.assertEqual(
            [row["id"] for row in response.json()["results"]],
            [source.pk],
        )

    def test_lookup_with_empty_code_returns_nothing(self):
        self.create_complete_source()
        response = self.client.get(
            reverse("quotes:item_latest_version", args=[self.target_quote.pk]),
            {"code": ""},
        )
        self.assertEqual(response.json()["results"], [])

    def test_lookup_returns_all_revisions_without_result_limit(self):
        code = "MOLTE-REV"
        for index in range(20):
            quote = Quote.objects.create(author=self.user)
            QuoteItem.objects.create(quote=quote, code=code, revision=f"{index:02d}")
        response = self.client.get(
            reverse("quotes:item_latest_version", args=[self.target_quote.pk]),
            {"code": "MOLTE"},
        )
        results = response.json()["results"]
        self.assertEqual(len(results), 20)
        self.assertEqual({row["revision"] for row in results}, {f"{index:02d}" for index in range(20)})

    def test_new_code_requires_revision(self):
        payload = self.new_item_payload(revision="")
        response = self.client.post(
            reverse("quotes:item_add", args=[self.target_quote.pk]),
            payload,
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Questo campo è obbligatorio", status_code=422)
        self.assertFalse(self.target_quote.items.filter(code="NUOVO-1").exists())

    def test_existing_code_requires_explicit_load_action(self):
        source = self.create_complete_source()
        payload = self.new_item_payload(code=source.code, revision=source.revision)
        response = self.client.post(reverse("quotes:item_add", args=[self.target_quote.pk]), payload)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Seleziona il risultato corrispondente", status_code=422)
        self.assertFalse(self.target_quote.items.exists())

    def test_same_code_with_new_revision_creates_new_combination(self):
        source = self.create_complete_source()
        payload = self.new_item_payload(code=source.code, revision="05")
        response = self.client.post(reverse("quotes:item_add", args=[self.target_quote.pk]), payload)
        self.assertRedirects(response, reverse("quotes:items", args=[self.target_quote.pk]))
        created = self.target_quote.items.get()
        self.assertEqual(created.code, source.code)
        self.assertEqual(created.revision, "05")
        self.assertIsNone(created.source_version)

    def test_selected_source_must_keep_its_code_and_revision(self):
        source = self.create_complete_source()
        response = self.client.post(
            reverse("quotes:item_add", args=[self.target_quote.pk]),
            self.clone_payload(source, revision="05"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "non corrisponde a codice e revisione", status_code=422)
        self.assertFalse(self.target_quote.items.exists())

    def test_double_submit_returns_same_version(self):
        source = self.create_complete_source()
        token = uuid.uuid4()
        payload = self.clone_payload(source, token=token)
        url = reverse("quotes:item_add", args=[self.target_quote.pk])
        self.client.post(url, payload)
        second = self.client.post(url, payload, follow=True)
        self.assertEqual(self.target_quote.items.filter(code=source.code).count(), 1)
        self.assertContains(second, "doppio invio è stato ignorato")

    def test_duplicate_action_creates_only_one_independent_row(self):
        source = self.create_complete_source()
        response = self.client.post(
            reverse("quotes:item_duplicate", args=[self.source_quote.pk, source.pk]),
        )
        self.assertRedirects(response, reverse("quotes:items", args=[self.source_quote.pk]))
        self.assertEqual(self.source_quote.items.count(), 2)
        copied = self.source_quote.items.exclude(pk=source.pk).get()
        self.assertEqual(copied.code, "ART-100-COPIA")
        self.assertEqual(copied.source_version, source)
        self.assertEqual(copied.materials.count(), source.materials.count())
        self.assertEqual(copied.phases.count(), source.phases.count())

    def test_article_date_migration_exists_after_timestamp_migration(self):
        migration = importlib.import_module("apps.quotes.migrations.0005_quoteitem_article_date")
        self.assertIn(("quotes", "0004_quoteitem_combined_key_search"), migration.Migration.dependencies)

    def test_quotes_code_never_uses_unique_get_lookup(self):
        quotes_root = Path(__file__).resolve().parents[1] / "apps" / "quotes"
        source = "\n".join(path.read_text(encoding="utf-8") for path in quotes_root.rglob("*.py"))
        self.assertNotIn(".get(code=", source)
        self.assertNotIn("get_or_create(code=", source)
        self.assertNotIn("update_or_create(code=", source)

    def test_superadmin_can_see_article_history(self):
        first = self.create_complete_source()
        second_quote = Quote.objects.create(author=self.user)
        second = QuoteItem.objects.create(
            quote=second_quote,
            code=first.code,
            revision=first.revision,
            source_version=first,
        )
        response = self.client.get(reverse("admin:quotes_quoteitem_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "storico articoli", html=False)
        self.assertContains(response, first.code)
        self.assertEqual(response.context["cl"].result_count, 2)
        self.assertIn("source_version", response.context["cl"].list_display)

    def test_regular_quote_pages_show_only_the_article_date(self):
        source = self.create_complete_source()
        copied, _ = create_article_version_from_latest(
            code=source.code,
            revision=source.revision,
            quote=self.target_quote,
        )
        items_response = self.client.get(reverse("quotes:items", args=[self.target_quote.pk]))
        work_response = self.client.get(reverse("quotes:work", args=[self.target_quote.pk]))
        for response in (items_response, work_response):
            self.assertNotContains(response, "Versione selezionata")
            self.assertNotContains(response, "Versione più recente")
            self.assertNotContains(response, "versione #")
            self.assertContains(response, copied.article_date.strftime("%d/%m/%Y"))

    def test_article_keys_are_not_editable_after_loading(self):
        source = self.create_complete_source()
        response = self.client.get(reverse("quotes:items", args=[self.source_quote.pk]))
        form = response.context["item_rows"][0]["item_form"]
        self.assertNotIn("code", form.fields)
        self.assertNotIn("revision", form.fields)
        self.assertNotIn("article_date", form.fields)

    def test_saving_article_changes_shows_a_green_confirmation(self):
        item = self.create_complete_source()
        prefix = f"item-{item.pk}"
        response = self.client.post(
            reverse("quotes:item_edit", args=[self.source_quote.pk, item.pk]),
            {
                f"{prefix}-quantity": "4",
                f"{prefix}-description": "Aggiornato",
                f"{prefix}-length_mm": item.length_mm,
                f"{prefix}-height_mm": item.height_mm,
                f"{prefix}-depth_mm": item.depth_mm,
                f"{prefix}-technical_notes": item.technical_notes,
                f"{prefix}-feasibility": item.feasibility,
            },
            follow=True,
        )
        self.assertContains(response, "Modifiche articolo salvate correttamente.")
        self.assertContains(response, 'class="message toast success"', html=False)
        self.assertEqual(response.context["open_item_id"], item.pk)
        self.assertEqual(
            response.request["QUERY_STRING"],
            f"open_item={item.pk}",
        )

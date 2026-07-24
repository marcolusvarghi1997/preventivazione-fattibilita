from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.quotes.models import Quote, QuoteItem


class QuoteResumeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_initial_data", verbosity=0)
        cls.user = get_user_model().objects.create_user("resume", password="pass")
        cls.user.groups.add(Group.objects.get(name="Commerciale"))

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_and_search_use_resume_link(self):
        quote = Quote.objects.create(author=self.user)
        resume_url = reverse("quotes:resume", args=[quote.pk])

        self.assertContains(self.client.get(reverse("quotes:dashboard")), resume_url, count=2)
        self.assertContains(self.client.get(reverse("quotes:search")), resume_url, count=2)

    def test_quote_without_articles_always_resumes_from_step_two(self):
        quote = Quote.objects.create(author=self.user, last_workflow_step=4)

        response = self.client.get(reverse("quotes:resume", args=[quote.pk]))

        self.assertRedirects(response, reverse("quotes:items", args=[quote.pk]))

    def test_resume_tracks_workflow_pages(self):
        quote = Quote.objects.create(author=self.user)
        QuoteItem.objects.create(quote=quote, code="RIPRESA", revision="00")

        self.client.get(reverse("quotes:work", args=[quote.pk]))
        self.assertRedirects(
            self.client.get(reverse("quotes:resume", args=[quote.pk])),
            reverse("quotes:work", args=[quote.pk]),
        )

        # Il materiale manca, quindi il riepilogo contiene errori: resta comunque il passo raggiunto.
        self.client.get(reverse("quotes:summary", args=[quote.pk]))
        self.assertRedirects(
            self.client.get(reverse("quotes:resume", args=[quote.pk])),
            reverse("quotes:summary", args=[quote.pk]),
        )

    def test_completed_quote_always_opens_summary(self):
        quote = Quote.objects.create(
            author=self.user,
            status=Quote.Status.COMPLETED,
            last_workflow_step=2,
        )

        self.assertRedirects(
            self.client.get(reverse("quotes:resume", args=[quote.pk])),
            reverse("quotes:summary", args=[quote.pk]),
        )

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone


PRODUCTION_STORAGES = {
    "staticfiles": {
        "BACKEND": "config.storage.JazzminCompatibleManifestStaticFilesStorage",
    },
}


class ProductionAdminStaticFilesTests(TestCase):
    @override_settings(DEBUG=False, STORAGES=PRODUCTION_STORAGES)
    def test_admin_renders_with_jazzmin_bootswatch_directory_reference(self):
        superuser = get_user_model().objects.create_superuser("static-admin", password="pass")
        self.client.force_login(superuser)
        self.assertEqual(self.client.get("/admin/").status_code, 200)


class InvalidSessionCleanupTests(TestCase):
    def test_command_removes_corrupted_session_and_preserves_valid_session(self):
        expires = timezone.now() + timedelta(days=1)
        store = SessionStore()
        Session.objects.create(
            session_key="v" * 32,
            session_data=store.encode({"user": "valido"}),
            expire_date=expires,
        )
        Session.objects.create(
            session_key="x" * 32,
            session_data="dati-sessione-non-validi",
            expire_date=expires,
        )

        call_command("cleanup_invalid_sessions", verbosity=0)

        self.assertTrue(Session.objects.filter(session_key="v" * 32).exists())
        self.assertFalse(Session.objects.filter(session_key="x" * 32).exists())

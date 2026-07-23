from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Elimina soltanto le sessioni scadute o non più decodificabili con la chiave corrente."

    def handle(self, *args, **options):
        if settings.SESSION_ENGINE != "django.contrib.sessions.backends.db":
            return

        Session.objects.filter(expire_date__lte=timezone.now()).delete()
        store = SessionStore()
        invalid_keys = []
        for session in Session.objects.only("session_key", "session_data").iterator():
            try:
                signing.loads(
                    session.session_data,
                    salt=store.key_salt,
                    serializer=store.serializer,
                )
            except Exception:
                invalid_keys.append(session.session_key)

        if invalid_keys:
            Session.objects.filter(session_key__in=invalid_keys).delete()
            if options["verbosity"]:
                self.stdout.write(
                    self.style.SUCCESS(f"Rimosse {len(invalid_keys)} sessioni non più valide.")
                )

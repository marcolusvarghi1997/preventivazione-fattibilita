from ipaddress import ip_address

from django.db import OperationalError, ProgrammingError
from django.http import HttpResponseForbidden

from .models import SiteConfiguration


class LanAccessMiddleware:
    """Blocca i client remoti quando l'accesso LAN è disattivato dal superadmin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        remote = request.META.get("REMOTE_ADDR", "127.0.0.1").split("%", 1)[0]
        try:
            is_loopback = ip_address(remote).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            try:
                lan_enabled = SiteConfiguration.load().lan_enabled
            except (OperationalError, ProgrammingError):
                lan_enabled = False
            if not lan_enabled:
                return HttpResponseForbidden(
                    "Accesso dalla rete locale disattivato. Il superadmin può abilitarlo dall'amministrazione."
                )
        return self.get_response(request)
